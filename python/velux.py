#!/usr/bin/python
# -*- coding: utf-8 -*-

# 2018 - Psychokiller1888 / Laurent Chervet
# If you find any bugs, please report on github
# If reusing keep credits


import logging

logging.basicConfig(
	format='%(asctime)s [%(threadName)s] - [%(levelname)s] - %(message)s',
	level=logging.INFO,
	filename='logs.log',
	filemode='w'
)

_logger = logging.getLogger('SnipsVelux')
_logger.addHandler(logging.StreamHandler())


import json
import math
import paho.mqtt.client as mqtt
import RPi.GPIO as gpio
from States import State
import sys
import time
import threading

###### REMOTE BUTTON SCHEME ######
# ----------
# | SCREEN |
# |        |
# ----------
# 1 - 2 - 3
# 4 - 5 - 6
#     7
#
#     8
#
#     9
#
#
#         10
#
# 1 = menu
# 2 = up arrow
# 3 = back
# 4 = p1
# 5 = down arrow
# 6 = p2
# 7 = up
# 8 = stop
# 9 = down
# 10 = reset (back side)
#
# Make sure you don't have any registered program!
# Make sure to turn off screen saving so the remote doesn't need waking up
# On start wait 12 seconds for booting

_RUNNING 		= True
_AS_SERVICE 	= False
_REED_RELAY 	= False


_MENU_PIN		= 33
_UP_ARROW_PIN	= 32
_BACK_PIN		= 31
_DOWN_ARROW_PIN = 36
_UP_PIN 		= 35
_STOP_PIN 		= 38
_DOWN_PIN 		= 37
_RESET_PIN 		= 40
_POWER_ON_PIN 	= 26


# Defines button press per actions
# Insert a string to add a pause after button click exemple: ['1', 3, 1] Would wait 1 seconds after each button click. Default wait time is 0.5
_COMMANDS = {
	'open': 					[7],
	'close': 					[9],
	'fullOpen': 				[7],
	'fullClose': 				[9],
	'selectAllWindows': 		['1.25', 3, '0.25', 1, 1,],
	'selectAllBlinders': 		['1.25', 3, '0.25', 1, 5, 1]
	#'selectBedroomWindows': 	['1.25', 3, '0.25', 5, 1, 1, 5, 5, 1],
	#'selectBathroomWindows': 	['1.25', 3, '0.25', 5, 5, 5, 1],
	#'selectRoomWindows': 		['1.25', 3, '0.25', 5, 5, 1, 5, 5, 1],
	#'selectBedroomBlinders': 	['1.25', 3, '0.25', 5, 1, 5, 1, 5, 5, 1]
}

_INTENT_OPEN_WINDOWS	= 'hermes/intent/Psychokiller1888:openVelux'
_INTENT_CLOSE_WINDOWS	= 'hermes/intent/Psychokiller1888:closeVelux'
_INTENT_OPEN_BLINDERS	= 'hermes/intent/Psychokiller1888:openBlinders'
_INTENT_CLOSE_BLINDERS	= 'hermes/intent/Psychokiller1888:closeBlinders'

_state 					= State.BOOTING
_commandPool 			= []

def onConnect(client, userdata, flags, rc):
	_mqttClient.subscribe(_INTENT_OPEN_WINDOWS)
	_mqttClient.subscribe(_INTENT_CLOSE_WINDOWS)
	_mqttClient.subscribe(_INTENT_OPEN_BLINDERS)
	_mqttClient.subscribe(_INTENT_CLOSE_BLINDERS)


def onMessage(client, userdata, message):
	global _state, _commandPool

	payload = json.loads(message.payload)
	sessionId = payload['sessionId']

	if _REED_RELAY and not gpio.input(_POWER_ON_PIN):
		_state = State.BOOTING
		gpio.output(_POWER_ON_PIN, gpio.HIGH)
		_commandPool.insert(len(_commandPool), message)
		t = threading.Timer(interval=15, function=executeAfterBoot, args=[])
		t.start()
		return

	if _state is not State.READY:
		_commandPool.insert(len(_commandPool), message)
		endTalk(sessionId=sessionId, text="I'm just a little busy but will do in a little while!")
		return

	place = 'all'
	if 'place' in payload and payload['place'] != 'all':
		place = payload['place']

	if message.topic == _INTENT_OPEN_WINDOWS:
		duration = 0
		if 'duration' in payload and payload['duration'] != 0:
			duration = payload['duration']['duration']

		percentage = 'full'
		if 'percentage' in payload and payload['percentage'] != 'full':
			percentage = payload['percentage'].replace('%', '')
			percentage = int(math.ceil(int(percentage) / 10.0)) * 10

		if percentage != 'full':
			openToCertainPercentage(percent=percentage, windows=place, duration=duration)
		else:
			fullOpen(what='windows', which=place, duration=duration)

		_logger.info('Opening windows (Payload was {})'.format(payload))

	elif message.topic == _INTENT_CLOSE_WINDOWS:
		when = 0
		if 'when' in payload and payload['when'] != 0:
			when = payload['when']['duration']

		if when == 0:
			fullClose(what='windows', which=place)
		else:
			thread = threading.Timer(when, fullClose, ['windows', place])
			thread.start()

		_logger.info('Closing windows (Payload was {})'.format(payload))

	elif message.topic == _INTENT_OPEN_BLINDERS:
		percentage = 'full'
		if 'percentage' in payload and payload['percentage'] != 'full':
			percentage = payload['percentage'].replace('%', '')
			percentage = int(math.ceil(int(percentage) / 10.0)) * 10

		if percentage != 'full':
			openBlindersToCertainPercentage(percent=percentage, blinders=place)
		else:
			fullOpen(what='blinders', which=place)

		_logger.info('Opening blinders (Payload was {})'.format(payload))

	elif message.topic == _INTENT_CLOSE_BLINDERS:
		percentage = 'full'
		if 'percentage' in payload and payload['percentage'] != 'full':
			percentage = payload['percentage'].replace('%', '')
			percentage = int(math.ceil(int(percentage) / 10.0)) * 10

		if percentage != 'full':
			openBlindersToCertainPercentage(percent=percentage, blinders=place)
		else:
			fullClose(what='blinders', which=place)
			_logger.info('Closing blinders (Payload was {})'.format(payload))
	else:
		_logger.warning('Unsupported message')

	endTalk(sessionId=sessionId, text='Ok, done!')


def endTalk(sessionId, text=''):
	_mqttClient.publish('hermes/dialogueManager/endSession', json.dumps({
		'sessionId': sessionId,
		'text': text
	}))


def stop():
	global _RUNNING
	_RUNNING = False


def executeAfterBoot():
	global _state, _commandPool
	_state = State.READY
	if len(_commandPool) > 0:
		onMessage(None, None, _commandPool.pop(0))


def fullOpen(what='windows', which='all', duration=0):
	global _COMMANDS
	setBusy()
	selectProduct(what, which)
	executeCommand(_COMMANDS['fullOpen'], cleanScreen=True)
	if what == 'windows' and duration > 0:
		thread = threading.Timer(duration, fullClose, ['windows', 'all'])
		thread.start()


def fullClose(what='windows', which='all'):
	global _COMMANDS
	setBusy()
	selectProduct(what, which)
	executeCommand(_COMMANDS['fullClose'], cleanScreen=True)


def selectProduct(what, which):
	global _COMMANDS
	str = 'select{}{}'.format(which.title(), what.title())
	if str not in _COMMANDS:
		str = 'selectAllWindows'
	executeCommand(_COMMANDS[str])


def openToCertainPercentage(percent, windows='all', duration=0):
	global _COMMANDS

	if percent == 0:
		fullClose(what='windows', which=windows)
		return
	elif percent == 10:
		timer = 3.3
	elif percent == 20:
		timer = 4.1
	elif percent == 30:
		timer = 4.8
	elif percent == 40:
		timer = 5.3
	elif percent == 50:
		timer = 6
	elif percent == 60:
		timer = 6.8
	elif percent == 70:
		timer = 7.4
	elif percent == 80:
		timer = 8.1
	elif percent == 90:
		timer = 8.8
	else:
		fullOpen(what='windows', which=windows, duration=duration)
		return

	setBusy()
	if duration > 0:
		thread = threading.Timer(duration, fullClose, ['windows', windows])
		thread.start()

	executeCommand(_COMMANDS['select{}Windows'.format(windows.title())])
	executeCommand(_COMMANDS['open'], clickTime=timer, cleanScreen=True)


def openBlindersToCertainPercentage(percent, blinders='all'):
	global _COMMANDS

	if percent == 0:
		fullClose(what='blinders', which=blinders)
		return
	elif percent == 10:
		timer = 1.8
	elif percent == 20:
		timer = 2.4
	elif percent == 30:
		timer = 3
	elif percent == 40:
		timer = 3.7
	elif percent == 50:
		timer = 4.6
	elif percent == 60:
		timer = 5.1
	elif percent == 70:
		timer = 5.8
	elif percent == 80:
		timer = 6.5
	elif percent == 90:
		timer = 7.3
	else:
		fullOpen(what='blinders', which=blinders)
		return

	setBusy()
	executeCommand(_COMMANDS['select{}Blinders'.format(blinders.title())])
	executeCommand(_COMMANDS['close'], clickTime=timer, cleanScreen=True)


def executeCommand(commandList, clickTime=0.2, cleanScreen=False):
	global _state

	waitTime = 0.5
	for cmd in commandList:
		if isinstance(cmd, basestring):
			waitTime = float(cmd)
			continue

		pin = translateButton(cmd)
		if pin == -1:
			break
		gpio.output(pin, gpio.HIGH)
		time.sleep(clickTime)
		gpio.output(pin, gpio.LOW)
		time.sleep(waitTime)

	if cleanScreen:
		if _REED_RELAY:
			_state = State.OFF
			time.sleep(1)
			gpio.output(_POWER_ON_PIN, gpio.LOW)
			time.sleep(1)
			executeCmdPool()
		else:
			time.sleep(1)
			reboot(State.READY)


def translateButton(buttonNumber):
	if buttonNumber == 1:
		return _MENU_PIN
	elif buttonNumber == 2:
		return _UP_ARROW_PIN
	elif buttonNumber == 3:
		return _BACK_PIN
	elif buttonNumber == 5:
		return _DOWN_ARROW_PIN
	elif buttonNumber == 7:
		return _UP_PIN
	elif buttonNumber == 8:
		return _STOP_PIN
	elif buttonNumber == 9:
		return _DOWN_PIN
	elif buttonNumber == 10:
		return _RESET_PIN
	else:
		_logger.warning('Unknown button: ' + str(buttonNumber))
		return -1


def setBusy():
	global _state
	_state = State.BUSY


def powerOn():
	global _state

	if _REED_RELAY:
		_logger.info('Reed relay mode: Remote controller off as long as not needed')
		_state = State.OFF
		_logger.info('Module ready')
	else:
		_logger.info('MOSFET mode: Starting remote controller')
		gpio.output(_POWER_ON_PIN, gpio.HIGH)
		threading.Timer(15, onRemoteStarted).start()


def onRemoteStarted():
	global _state
	_state = State.READY
	_logger.info('Module ready')


def setupGpio():
	gpio.setmode(gpio.BOARD)
	gpio.setwarnings(False)
	gpio.setup(_MENU_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_UP_ARROW_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_BACK_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_DOWN_ARROW_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_UP_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_STOP_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_DOWN_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_RESET_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)
	gpio.setup(_POWER_ON_PIN, gpio.OUT, gpio.PUD_OFF, gpio.LOW)


def reset():
	global _state
	_state = State.RESETTING
	gpio.output(_POWER_ON_PIN, gpio.LOW)
	time.sleep(2)
	gpio.output(_RESET_PIN, gpio.HIGH)
	gpio.output(_POWER_ON_PIN, gpio.HIGH)
	time.sleep(6)
	gpio.output(_RESET_PIN, gpio.LOW)
	_state = State.READY


def reboot(toState):
	global _state
	gpio.output(_POWER_ON_PIN, gpio.LOW)
	_state = State.OFF
	time.sleep(2)
	gpio.output(_POWER_ON_PIN, gpio.HIGH)
	_state = State.BOOTING
	time.sleep(12)
	_state = toState
	executeCmdPool()


def executeCmdPool():
	global _commandPool
	if len(_commandPool) > 0:
		onMessage(None, None, _commandPool.pop(0))


if __name__ == '__main__':
	_logger.info('Powering Velux remote, please wait until ready')

	if len(sys.argv) > 1 and sys.argv[1] == 1:
		_AS_SERVICE = True

	if len(sys.argv) > 2 and sys.argv[2] == 1:
		_REED_RELAY = True

	setupGpio()
	powerOn()
	_mqttClient = mqtt.Client()
	_mqttClient.on_connect = onConnect
	_mqttClient.on_message = onMessage
	_mqttClient.connect('localhost', 1883)
	_mqttClient.loop_start()
	try:
		if not _AS_SERVICE:
			while _RUNNING:
				if  _state is State.READY:
					button = raw_input('Type a button number: ')
					try:
						button = int(button)
					except ValueError:
						if button == 'reset':
							reset()
							continue
						else:
							_logger.warning('Please use numbers from 1 to 10 only (or `reset`)')
							continue

					pin = translateButton(button)
					if pin != -1:
						gpio.output(pin, gpio.HIGH)
						time.sleep(0.25)
						gpio.output(pin, gpio.LOW)
						time.sleep(0.25)
		else:
			while _RUNNING:
				time.sleep(0.1)

		raise KeyboardInterrupt
	except KeyboardInterrupt:
		pass
	finally:
		_logger.info('Stopping Velux Snips module')
		_mqttClient.loop_stop()
		gpio.cleanup()