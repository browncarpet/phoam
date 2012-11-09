#!/usr/bin/python
###############################################################################
##
##
##
###############################################################################

import sys, serial
from threading import Thread
from twisted.internet import reactor
from twisted.python import log
from twisted.web.server import Site
from twisted.web.static import File

from autobahn.websocket import WebSocketServerFactory, \
                               WebSocketServerProtocol, \
                               listenWS

msgList = []
comBuffer = []
comQueue = []
hvacZone = ''

tekmar = serial.Serial(
	port='/dev/ttyS0',
	baudrate = 9600,
	timeout=1
)

tekmar.close()
tekmar.open()
if tekmar.isOpen():
	print 'Tekmar Connected!'
	#tekmar.write('##%a507A=1,R=1')

hvacList = ['hvac.1.name.Living Room','hvac.1.temp.74','hvac.1.max.80','hvac.1.min.68','hvac.1.mode.Auto']  
  
class tekmarRead(Thread):
	name = 'readHVACThread'
	def run(self):
		x = 1
		global comBuffer, comQueue
		while x is 1 :
			fromtekmar = tekmar.read()
			if fromtekmar != '':
				#print fromtekmar
				if '\r' not in fromtekmar:
					comBuffer.append(fromtekmar)
				else:
					try:
						x = 0
						comQueue.append(comBuffer)
						b = comQueue.pop()
						data = ''.join(b)
						print data
						if 'A=00' in data:
							try:							
								rcsToWeb(data)
							except:
								factory.broadcast('Bad A= String')
						elif '##0' in data:
							pass
						#elif data[14:16] == 'R5':
							#pass
						elif data[14:16] == 'd0':
							factory.broadcast(cmdToWeb(data))
						elif data[14] == 'b':
							factory.broadcast(cmdToWeb(data))
						else:
							pass
					except:
						if tekmarRead().isAlive():
							print 'thread still alive'
						else:
							print 'thread dead'
							tekmarRead().start()
						raise
					finally:
						comBuffer = []
						x = 1
				
#Interpretations between RCS and Web through RCS 485 controller and Comstar

def webToRCS(command):
	methodList = {'mint':'SPH=','maxt':'SPC=','mode':'M='}
	addy = command[4:6]
	method = command[6:10]
	data = command[10:14]
	commandString = "A="+addy+" "+methodList[method]+data
	return commandString
				
def rcsToWeb(command):
	modeList = {'A':'Auto','O':'Off','C':'Cool','H':'Heat'}
	updateList = []
	addy = command[command.index(' O=')+3:command.index(' O=')+5]
	if addy[1] == ' ':
		addy = '0' + addy[0]
	temp = command[command.index(' T=')+3:command.index(' T=')+6]
	mode = command[command.index(' M=')+3:command.index(' M=')+4]
	sph = command[command.index(' SPH=')+5:command.index(' SPH=')+8]
	spc = command[command.index(' SPC=')+5:command.index(' SPC=')+8]
	updateList.append('hvac'+addy+'temp'+temp)
	updateList.append('hvac'+addy+'mode'+modeList[mode])
	updateList.append('hvac'+addy+'maxt'+spc)
	updateList.append('hvac'+addy+'mint'+sph)
	for c in updateList:
		factory.broadcast(c)
	
	
def cmdToWeb(command):
	global hvacZone
	methodList = {'b0':'temp', 'b9':'maxt', 'b8':'mint', 'b3':'mode', 'b1':'none', 'b6':'none', 'b4':'fans'}
	modeList = {'00':'Off', '01':'Heat', '02':'Cool','03':'Auto'}
	#added additional index increment because of leading <LF> or \n we can't see
	if command[14:16] == 'd0':
		hvacZone = str(int(int(command[16:18], 16) + 1))
		if len(hvacZone) < 2:
			hvacZone = '0'+hvacZone
		print 'Current HVAC Addr: '+hvacZone
		return 'hvac00modeAuto'
	if command[14] == 'b':
		data = int(command[16:18], 16)
		method = methodList[command[14:16]]
		if method == 'mode':
			data = modeList[command[16:18]]
		webString = 'hvac'+hvacZone+method+str(data)
		return webString

def webToCmd(command):
  methodList = {'mint':'c0','maxt':'e0','mode':'30'}
  modeList = {'Off':'01', 'Heat':'02', 'Cool':'03','Auto':'04'}
  addy = str(int(command[4:6])-1)
  if len(addy) < 2:
		addy = '0'+ addy
  method = command[6:10]
  rawData = command[10:14]
  if method == 'mode':
    data = modeList[rawData]
  else:
    data = hex(int(rawData))[2:4]
  commandString = '##%5e'+addy+methodList[method]+data
  return commandString
				
class BroadcastServerProtocol(WebSocketServerProtocol):

	def onOpen(self):
		self.factory.register(self)

	def onMessage(self, msg, binary):
		if not binary:
			global msgList
			#self.factory.broadcast("'%s' from %s" % (msg, self.peerstr))
			self.factory.broadcast(msg)
			tekmar.write(webToCmd(msg)+"\r")

	def connectionLost(self, reason):
		WebSocketServerProtocol.connectionLost(self, reason)
		self.factory.unregister(self)


class BroadcastServerFactory(WebSocketServerFactory):
	"""
	Simple broadcast server broadcasting any message it receives to all
	currently connected clients.
	"""

	def __init__(self, url, debug = False, debugCodePaths = False):
		WebSocketServerFactory.__init__(self, url, debug = debug, debugCodePaths = debugCodePaths)
		self.clients = []
		self.tickcount = 0
		self.tick()

	def tick(self):
		self.tickcount += 1
		self.broadcast("'tick %d' from server" % self.tickcount)
		reactor.callLater(5, self.tick)

	def register(self, client):
		if not client in self.clients:
			tekmar.write('##%a507A=1,R=1\r')
			print "registered client " + client.peerstr
			self.clients.append(client)
			
		 

	def unregister(self, client):
		if client in self.clients:
			print "unregistered client " + client.peerstr
			self.clients.remove(client)

	def broadcast(self, msg):
		print "broadcasting message '%s' .." % msg
		for c in self.clients:
			c.sendMessage(msg)
			print "message sent to " + c.peerstr



class BroadcastPreparedServerFactory(BroadcastServerFactory):
	"""
	Functionally same as above, but optimized broadcast using
	prepareMessage and sendPreparedMessage.
	"""

	def broadcast(self, msg):
		print "broadcasting prepared message '%s' .." % msg
		preparedMsg = self.prepareMessage(msg)
		for c in self.clients:
			c.sendPreparedMessage(preparedMsg)
			print "prepared message sent to " + c.peerstr



tekmarRead().start()		 
		 
if __name__ == '__main__':

	if len(sys.argv) > 1 and sys.argv[1] == 'debug':
		log.startLogging(sys.stdout)
		debug = True
	else:
		debug = False

	ServerFactory = BroadcastServerFactory
	#ServerFactory = BroadcastPreparedServerFactory

	factory = ServerFactory("ws://localhost:9000",
												 debug = debug,
												 debugCodePaths = debug)

	factory.protocol = BroadcastServerProtocol
	factory.setProtocolOptions(allowHixie76 = True)
	listenWS(factory)

	webdir = File(".")
	web = Site(webdir)
	reactor.listenTCP(8081, web)

	reactor.run()
