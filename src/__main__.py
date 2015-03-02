# -*- coding: utf-8 -*-
# I ought to clean these imports up a bit.
import socket, datetime, time, sys, threading, random, subprocess, os, json, signal, traceback, ConfigParser, proxy, web, globals, storage, hashlib, cProfile, md5, uuid
from log import *
from config import Config
from irc import IRC
from server import Server
from importlib import import_module
from scripts import Scripts
from api import API
from uuid import UUID
from plugins import Plugins
from commands import Commands
from events import Events
# I'm not 100% sure if readline works under Windows or not
try: import readline
except: pass
# Sloppy import catch system
try:
	import requests
	IMPORT_REQUESTS = True
except:
	IMPORT_REQUESTS = False

class Wrapper:
	def __init__(self):
		self.log = Log()
		self.configManager = Config(self.log)
		self.server = False
		self.proxy = False
		self.halt = False
		self.update = False
		self.storage = storage.Storage("main", self.log)
		self.permissions = storage.Storage("permissions", self.log)
		self.usercache = storage.Storage("usercache", self.log)
		
		self.plugins = Plugins(self)
		self.commands = Commands(self)
		self.events = Events(self)
		self.permission = {}
		self.help = {}
		
		# Aliases for compatibility 
		self.callEvent = self.events.callEvent
	def isOnlineMode(self):
		if self.config["Proxy"]["proxy-enabled"]:
			return self.config["Proxy"]["online-mode"]
		if self.server:
			if self.server.onlineMode: return True
		return False
	def UUIDFromName(self, name):
		m = md5.new()
		m.update("OfflinePlayer:"+name)
		d = bytearray(m.digest())
		d[6] &= 0x0f
		d[6] |= 0x30
		d[8] &= 0x3f
		d[8] |= 0x80
		return uuid.UUID(bytes=str(d))
	def getUsername(self, uuid):
		if type(uuid) not in (str, unicode): return False
		if self.isOnlineMode():
			if self.proxy:
				obj = self.proxy.lookupUUID(uuid)
				if obj: return str(obj["name"])
			if uuid in self.usercache:
				if "name" in self.usercache[uuid]:
					return str(self.usercache[uuid]["name"])
			try:
				r = requests.get("https://api.mojang.com/user/profiles/%s/names" % uuid.replace("-", "")).json()
				username = r[0]["name"]
				if not uuid in self.usercache:
					self.usercache[uuid] = {"time": time.time(), "name": None, "online": True}
				if username != self.usercache[uuid]["name"]:
					self.usercache[uuid]["name"] = username
					self.usercache[uuid]["online"] = True
					self.usercache[uuid]["time"] = time.time()
				return str(username)
			except: return False
		else:
			f = open("usercache.json", "r")
			data = json.loads(f.read())
			f.close()
			for u in data:
				if u["uuid"] == uuid:
					if not uuid in self.usercache:
						self.usercache[uuid] = {"time": time.time(), "name": None}
					if u["name"] != self.usercache[uuid]["name"]:
						self.usercache[uuid]["name"] = u["name"]
						self.usercache[uuid]["online"] = False
						self.usercache[uuid]["time"] = time.time()
					return str(u["name"])
	def getUUID(self, username):
		""" Unfinished function. Needs finishing pronto! """
		if self.isOnlineMode():
			pass
		else:
			return self.UUIDFromName(username)
		if not self.proxy:
			f = open("usercache.json", "r")
			data = json.loads(f.read())
			f.close()
			for u in data:
				if u["name"] == username:
					return u["uuid"]
		return False
	def start(self):
		self.configManager.loadConfig()
		self.config = self.configManager.config
		signal.signal(signal.SIGINT, self.SIGINT)
		signal.signal(signal.SIGTERM, self.SIGINT)
		
		self.api = API(self, "Wrapper.py")
		self.api.registerHelp("Wrapper", "Internal Wrapper.py commands ", [
			("/wrapper [update/memory/halt]", "If no subcommand is provided, it'll show the Wrapper version.", None),
			("/plugins", "Show a list of the installed plugins", None),
			("/permissions <groups/users/RESET>", "Command used to manage permission groups and users, add permission nodes, etc.", None),
			("/playerstats [all]", "Show the most active players. If no subcommand is provided, it'll show the top 10 players.", None),
			("/reload", "Reload all plugins.", None)
		])
		
		self.server = Server(sys.argv, self.log, self.configManager.config, self)
		self.server.init()
		
		self.plugins.loadPlugins()
		
		if self.config["IRC"]["irc-enabled"]:
			self.irc = IRC(self.server, self.config, self.log, self, self.config["IRC"]["server"], self.config["IRC"]["port"], self.config["IRC"]["nick"], self.config["IRC"]["channels"])
			t = threading.Thread(target=self.irc.init, args=())
			t.daemon = True
			t.start()
		if self.config["Web"]["web-enabled"]:
			if web.IMPORT_SUCCESS:
				self.web = web.Web(self)
				t = threading.Thread(target=self.web.wrap, args=())
				t.daemon = True
				t.start()
			else:
				self.log.error("Web remote could not be started because you do not have the required modules installed: pkg_resources")
				self.log.error("Hint: http://stackoverflow.com/questions/7446187")
		if len(sys.argv) < 2:
			wrapper.server.args = wrapper.configManager.config["General"]["command"].split(" ")
		else:
			wrapper.server.args = sys.argv[1:]
		
		consoleDaemon = threading.Thread(target=self.console, args=())
		consoleDaemon.daemon = True
		consoleDaemon.start()
		
		t = threading.Thread(target=self.timer, args=())
		t.daemon = True
		t.start()
		
		if self.config["General"]["shell-scripts"]:
			if os.name in ("posix", "mac"):
				self.scripts = Scripts(self)
			else:
				self.log.error("Sorry, but shell scripts only work on *NIX-based systems! If you are using a *NIX-based system, please file a bug report.")
		
		if self.config["Proxy"]["proxy-enabled"]:
			t = threading.Thread(target=self.startProxy, args=())
			t.daemon = True
			t.start()
		if self.config["General"]["auto-update-wrapper"]:
			t = threading.Thread(target=self.checkForUpdates, args=())
			t.daemon = True
			t.start()
		self.server.__handle_server__()
		
		self.plugins.disablePlugins()
	def startProxy(self):
		if proxy.IMPORT_SUCCESS:
			self.proxy = proxy.Proxy(self)
			proxyThread = threading.Thread(target=self.proxy.host, args=())
			proxyThread.daemon = True
			proxyThread.start()
		else:
			self.log.error("Proxy mode could not be started because you do not have one or more of the following modules installed: pycrypt and requests")
	def SIGINT(self, s, f):
		self.shutdown()
	def shutdown(self, status=0):
		self.halt = True
		self.server.stop(reason="Wrapper.py Shutting Down", save=False)
		time.sleep(1)
		sys.exit(status)
	def rebootWrapper(self):
		self.halt = True
		os.system(" ".join(sys.argv) + "&")
	def getBuildString(self):
		if globals.type == "dev":
			return "%s (development build #%d)" % (Config.version, globals.build)
		else:
			return "%s (stable)" % Config.version
	def checkForUpdates(self):
		if not IMPORT_REQUESTS:
			self.log.error("Can't automatically check for new Wrapper.py versions because you do not have the requests module installed!")
			return
		while not self.halt:
			time.sleep(3600)
			self.checkForUpdate(True)
	def checkForUpdate(self, auto):
		self.log.info("Checking for new builds...")
		update = self.checkForNewUpdate()
		if update:
			version, build, type = update
			if type == "dev":
				if auto and not self.config["General"]["auto-update-dev-build"]:
					self.log.info("New Wrapper.py development build #%d available for download! (currently on #%d)" % (build, globals.build))
					self.log.info("Because you are running a development build, you must manually update Wrapper.py To update Wrapper.py manually, please type /update-wrapper.")
				else:
					self.log.info("New Wrapper.py development build #%d available! Updating... (currently on #%d)" % (build, globals.build))
				self.performUpdate(version, build, type)
			else:
				self.log.info("New Wrapper.py stable %s available! Updating... (currently on %s)" % (".".join([str(_) for _ in version]), Config.version))
				self.performUpdate(version, build, type)
		else:
			self.log.info("No new versions available.")
	def checkForNewUpdate(self, type=None):
		if type == None: type = globals.type
		if type == "dev":
			try:
				r = requests.get("https://raw.githubusercontent.com/benbaptist/minecraft-wrapper/development/docs/version.json")
				data = r.json()
				if self.update: 
					if self.update > data["build"]: return False
				if data["build"] > globals.build and data["type"] == "dev": return (data["version"], data["build"], data["type"])
				else: return False
			except:
				self.log.warn("Failed to check for updates - are you connected to the internet?")
		else:
			try:
				r = requests.get("https://raw.githubusercontent.com/benbaptist/minecraft-wrapper/master/docs/version.json")
				data = r.json()
				if self.update: 
					if self.update > data["build"]: return False
				if data["build"] > globals.build and data["type"] == "stable":  return (data["version"], data["build"], data["type"])
				else: return False
			except:
				self.log.warn("Failed to check for updates - are you connected to the internet?")
		return False
	def performUpdate(self, version, build, type):
		if type == "dev": repo = "development"
		else: repo = "master"
		try:
			wrapperHash = requests.get("https://raw.githubusercontent.com/benbaptist/minecraft-wrapper/%s/docs/Wrapper.py.md5" % repo).text
			wrapperFile = requests.get("https://raw.githubusercontent.com/benbaptist/minecraft-wrapper/%s/Wrapper.py" % repo).content
			self.log.info("Verifying Wrapper.py...")
			if hashlib.md5(wrapperFile).hexdigest() == wrapperHash:
				self.log.info("Update file successfully verified. Installing...")
				with open(sys.argv[0], "w") as f:
					f.write(wrapperFile)
				self.log.info("Wrapper.py %s (#%d) installed. Please reboot Wrapper.py." % (".".join([str(_) for _ in version]), build))
				self.update = build
				return True
			else:
				return False
		except:
			self.log.error("Failed to update due to an internal error:")
			self.log.getTraceback()
			return False
	def timer(self):
		while not self.halt:
			self.callEvent("timer.second", None)
			time.sleep(1)
	def console(self):
		while not self.halt:
			input = raw_input("")
			if len(input) < 1: continue
			if input[0] is not "/": 
				try:
					self.server.console(input)
				except:
					break
				continue
			def args(i): 
				try: return input[1:].split(" ")[i]
				except: pass
			def argsAfter(i): 
				try: return " ".join(input[1:].split(" ")[i:]);
				except: pass;
			command = args(0)
			if command == "halt":
				self.server.stop("Halting server...", save=False)
				self.halt = True
				sys.exit()
			elif command == "stop":
				self.server.stop("Stopping server...")
			elif command == "start":
				self.server.start()
			elif command == "restart":
				self.server.restart("Server restarting, be right back!")
			elif command == "reload":
				self.plugins.reloadPlugins()
				if self.server.getServerType() != "vanilla":
					self.log.info("Note: If you meant to reload the server's plugins instead of the Wrapper's plugins, try running `reload` without any slash OR `/raw /reload`.")
			elif command == "update-wrapper":
				self.checkForUpdate(False)
			elif command == "plugins":
				self.log.info("List of Wrapper.py plugins installed:")
				for id in self.plugins:
					plugin = self.plugins[id]
					if plugin["good"]:
						name = plugin["name"]
						summary = plugin["summary"]
						if summary == None: summary = "No description available for this plugin"
						
						version = plugin["version"]
							
						self.log.info("%s v%s - %s" % (name, ".".join([str(_) for _ in version]), summary))
					else:
						self.log.info("%s failed to load!" % (plug))
			elif command in ("mem", "memory"):
				if self.server.getMemoryUsage():
					self.log.info("Server Memory Usage: %d bytes" % self.server.getMemoryUsage())
				else:
					self.log.error("Server not booted or another error occurred while getting memory usage!")
			elif command == "raw":
				if self.server.state in (1, 2, 3):
					if len(argsAfter(1)) > 0:
						self.server.console(argsAfter(1))
					else:
						self.log.info("Usage: /raw [command]")
				else:
					self.log.error("Server is not started. Please run `/start` to boot it up.")
			elif command == "freeze":
				if not self.server.state == 0:
					self.server.freeze()
				else:
					self.log.error("Server is not started. Please run `/start` to boot it up.")	
			elif command == "unfreeze":
				if not self.server.state == 0:
					self.server.unfreeze()
				else:
					self.log.error("Server is not started. Please run `/start` to boot it up.")	
			elif command == "help":
				self.log.info("/reload - Reload plugins")	
				self.log.info("/plugins - Lists plugins")	
				self.log.info("/update-wrapper - Checks for new updates, and will install them automatically if one is available")
				self.log.info("/start & /stop - Start and stop the server without auto-restarting respectively without shutting down Wrapper.py")
				self.log.info("/restart - Restarts the server, obviously")				
				self.log.info("/halt - Shutdown Wrapper.py completely")
				self.log.info("/freeze & /unfreeze - Temporarily locks the server up until /unfreeze is executed")
				self.log.info("/mem - Get memory usage of the server")
				self.log.info("/raw [command] - Send command to the Minecraft Server. Useful for Forge commands like `/fml confirm`.")
				self.log.info("Wrapper.py Version %s" % self.getBuildString())
			else:
				self.log.error("Invalid command %s" % command)
if __name__ == "__main__":
	wrapper = Wrapper()
	log = wrapper.log
	log.info("Wrapper.py started - Version %s" % wrapper.getBuildString())
	
	try:
		wrapper.start()
	except SystemExit:
		#log.error("Wrapper.py received SystemExit")
		if not wrapper.configManager.exit:
			os.system("reset")
		wrapper.plugins.disablePlugins()
		wrapper.halt = True
		try:
			wrapper.server.console("save-all")
			wrapper.server.stop("Wrapper.py received shutdown signal - bye", save=False)
		except:
			pass
	except:
		log.error("Wrapper.py crashed - stopping server to be safe")
		for line in traceback.format_exc().split("\n"):
			log.error(line)
		wrapper.halt = True
		wrapper.plugins.disablePlugins()
		try:
			wrapper.server.stop("Wrapper.py crashed - please contact the server host instantly", save=False)
		except:
			print "Failure to shut down server cleanly! Server could still be running, or it might rollback/corrupt!"
