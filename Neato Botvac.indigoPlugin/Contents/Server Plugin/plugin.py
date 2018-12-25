#! /usr/bin/env python
# -*- coding: utf-8 -*-
################################################################################

import indigo

import threading
import Queue
import time

from pybotvac import Account
from pybotvac import Robot

################################################################################
# globals
k_robot_state = {
    0:    'invalid',
    1:    'idle',
    2:    'busy',
    3:    'paused',
    4:    'error'
    }
k_robot_action = {
    0:  'none',
    1:    'house_cleaning',
    2:    'spot_cleaning',
    3:    'manual_cleaning',
    4:    'docking',
    5:    'user_menu_active',
    6:    'suspended_cleaning',
    7:    'updating',
    8:    'copying_logs',
    9:    'recovering_location',
    10:    'iec_test',
    11:    'map_cleaning',
    12:    'exploring_map',
    13:    'acquiring_persistent_maps',
    14:    'creating_uploading_map',
    15: 'suspended_exploration'
    }
k_robot_cleaning_category = {
    1:  'manual',
    2:  'house',
    3:  'spot'
    }
k_robot_cleaning_mode = {
    1:  'eco',
    2:  'turbo',
    }
k_robot_cleaning_modifier = {
    1:  'normal',
    2:  'double',
    }
k_robot_cleaning_navigation = {
    1:  'normal',
    2:  'extra_care',
    3:  'deep'
    }

################################################################################
class Plugin(indigo.PluginBase):

    #-------------------------------------------------------------------------------
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.account = None

    #-------------------------------------------------------------------------------
    # start, stop and plugin config
    #-------------------------------------------------------------------------------
    def startup(self):
        self.updateAccount()

        self.debug = self.pluginPrefs.get('showDebugInfo',False)
        if self.debug:
            self.logger.debug(u'Debug logging enabled')

        self.instance_dict = dict()

        # indigo.devices.subscribeToChanges()

    #-------------------------------------------------------------------------------
    def shutdown(self):
        self.pluginPrefs['showDebugInfo'] = self.debug

    #-------------------------------------------------------------------------------
    def validatePrefsConfigUi(self, valuesDict):
        errorsDict = indigo.Dict()

        for key in ['email','password']:
            if not valuesDict.get(key,''):
                errorsDict[key] = u'Required'

        if len(errorsDict) > 0:
            self.logger.debug(u'validate plugin config error: \n{}'.format(errorsDict))
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.updateAccount()
            self.debug = valuesDict.get('showDebugInfo',False)
            if self.debug:
                self.logger.debug(u'Debug logging enabled')

    #-------------------------------------------------------------------------------
    def runConcurrentThread(self):
        try:
            while True:
                loop_time = time.time()
                for instance in self.instance_dict.values():
                    instance.task(instance.tick)
                self.sleep(1)
        except self.StopThread:
            pass

    #-------------------------------------------------------------------------------
    # subscribed changes
    #-------------------------------------------------------------------------------
    # def deviceUpdated(self, old_dev, new_dev):
    #     if new_dev.pluginId == self.pluginId:
    #         # device belongs to plugin
    #         indigo.PluginBase.deviceUpdated(self, old_dev, new_dev)
    #         if new_dev.configured:
    #             self.instance_dict[new_dev.id].task(instance.selfUpdated, new_dev)

    #-------------------------------------------------------------------------------
    # menu methods
    #-------------------------------------------------------------------------------
    def updateAccount(self):
        email = self.pluginPrefs.get('email','')
        password = self.pluginPrefs.get('password','')

        if email and password:
            try:
                self.account = Account(email, password)
                self.logger.info(u'Neato account updated')
                if len(self.account.robots) > 0:
                    self.logger.info(u'Robots found:')
                    for robot in self.account.robots:
                        self.logger.info(u'     {} ({})'.format(robot.name, robot.serial))
                else:
                    self.logger.error(u'No robots found')
            except:
                self.logger.error(u'Error accessing Neato account - check plugin config')

        else:
            # plugin is not configured
            self.logger.error(u'No account credentials - check plugin config')

    #-------------------------------------------------------------------------------
    def toggleDebug(self):
        if self.debug:
            self.logger.debug(u'Debug logging disabled')
            self.debug = False
        else:
            self.debug = True
            self.logger.debug(u'Debug logging enabled')

    #-------------------------------------------------------------------------------
    # device methods
    #-------------------------------------------------------------------------------
    def deviceStartComm(self, dev):
        if dev.configured:
            dev.stateListOrDisplayStateIdChanged()
            if dev.deviceTypeId == 'NeatoBotvac':
                self.instance_dict[dev.id] = Botvac(dev, self.logger)

    #-------------------------------------------------------------------------------
    def deviceStopComm(self, dev):
        if dev.id in self.instance_dict:
            self.instance_dict[dev.id].cancel()
            while self.instance_dict[dev.id].is_alive():
                time.sleep(0.1)
            del self.instance_dict[dev.id]

    #-------------------------------------------------------------------------------
    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        errorsDict = indigo.Dict()

        if not valuesDict.get('serial',None):
            errorsDict['serial'] = u'Required'
        else:
            for robot in self.account.robots:
                if valuesDict['serial'] == robot.serial:
                    valuesDict['secret'] = robot.secret
                    valuesDict['traits'] = robot.traits
                    valuesDict['name'] = robot.name
                    valuesDict['address'] = robot.serial
                    break
            else:
                errorsDict['serial'] = u'Robot not found.  Update account and try again.'

        if len(errorsDict) > 0:
            self.logger.debug(u'validate device config error: \n{}'.format(errorsDict))
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    # device config callbacks
    #-------------------------------------------------------------------------------
    def getRobotList(self, filter=None, valuesDict=None, typeId='', targetId=0):
        return [(robot.serial,robot.name) for robot in self.account.robots]

    #-------------------------------------------------------------------------------
    # action methods
    #-------------------------------------------------------------------------------
    def validateActionConfigUi(self, valuesDict, typeId, devId, runtime=False):
        errorsDict = indigo.Dict()

        if typeId == 'start_spot_cleaning':
            for key in ['width','height']:
                if not validateTextFieldNumber(valuesDict[key], numType=int, zero=False, negative=False):
                    errorsDict[key] = 'Must be positive integer'

        if len(errorsDict) > 0:
            self.logger.debug(u'validate action config error: \n{}'.format(errorsDict))
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    # action control
    #-------------------------------------------------------------------------------
    def actionControlUniversal(self, action, dev):
        instance = self.instance_dict[dev.id]

        # STATUS REQUEST
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.logger.info('"{}" status update'.format(dev.name))
            instance.task(instance.requestStatus)
        # UNKNOWN
        else:
            self.logger.debug(u'"{}" {} request ignored'.format(dev.name, action.deviceAction))

    #-------------------------------------------------------------------------------
    # action callbacks
    #-------------------------------------------------------------------------------
    def start_cleaning(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.start_cleaning, action.props)

    #-------------------------------------------------------------------------------
    def start_spot_cleaning(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.start_spot_cleaning, action.props)

    #-------------------------------------------------------------------------------
    def pause_cleaning(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.pause_cleaning)

    #-------------------------------------------------------------------------------
    def resume_cleaning(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.resume_cleaning)

    #-------------------------------------------------------------------------------
    def stop_cleaning(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.stop_cleaning)

    #-------------------------------------------------------------------------------
    def send_to_base(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.send_to_base)

    #-------------------------------------------------------------------------------
    def enable_schedule(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.enable_schedule)

    #-------------------------------------------------------------------------------
    def disable_schedule(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.disable_schedule)

    #-------------------------------------------------------------------------------
    def get_schedule(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.get_schedule)

    #-------------------------------------------------------------------------------
    def locate(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.locate)

    #-------------------------------------------------------------------------------
    def get_general_info(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.get_general_info)

    #-------------------------------------------------------------------------------
    def get_local_stats(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.get_local_stats)

    #-------------------------------------------------------------------------------
    def get_preferences(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.get_preferences)

    #-------------------------------------------------------------------------------
    def get_map_boundaries(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.get_map_boundaries)

    #-------------------------------------------------------------------------------
    def get_robot_info(self, action):
        instance = self.instance_dict[action.deviceId]
        instance.task(instance.get_robot_info)

###############################################################################
# Classes
###############################################################################
class Botvac(threading.Thread):
    # class properties
    k_update_states = ['state','robot_name']

    #-------------------------------------------------------------------------------
    def __init__(self, device, logger):
        super(Botvac, self).__init__()
        self.daemon     = True
        self.cancelled  = False
        self.queue      = Queue.Queue()

        self.logger = logger

        self.device = device
        self.props  = device.pluginProps
        self.robot  = Robot(self.props['serial'],self.props['secret'],self.props['traits'],self.props['name'])

        self.frequency = int(self.props.get('statusFrequency','120'))

        self.states = dict()
        self.available_commands = dict()
        self.next_update = 0

        self.task(self.requestStatus)
        self.start()

    #-------------------------------------------------------------------------------
    def run(self):
        self.logger.debug('"{}" thread started'.format(self.name))
        while not self.cancelled:
            try:
                func, args = self.queue.get(True,2)
                try:
                    func(*args)
                except NotImplementedError:
                    self.logger.error('"{}" task "{}" not implemented'.format(self.name,func.__name__))
                self.queue.task_done()
            except Queue.Empty:
                pass
            except Exception as e:
                self.logger.exception('"{}" thread error \n{}'.format(self.name, e))
        else:
            self.logger.debug('"{}" thread cancelled'.format(self.name))

    #-------------------------------------------------------------------------------
    def task(self, func, *args):
        self.queue.put((func, args))
        # func(*args)

    #-------------------------------------------------------------------------------
    def cancel(self):
        self.cancelled = True

    #-------------------------------------------------------------------------------
    # def selfUpdated(self, new_dev):
    #     self.device = new_dev
    #     self.states = new_dev.states
    #     self.props  = new_dev.pluginProps

    #-------------------------------------------------------------------------------
    def tick(self):
        if time.time() >= self.next_update:
            self.requestStatus()

    #-------------------------------------------------------------------------------
    def requestStatus(self):
        self.logger.info(u'"{}" request status'.format(self.name))
        robot_status = self.robot.state

        self.states['state']            = k_robot_state[robot_status['state']]
        self.states['action']           = k_robot_action[robot_status['action']]
        self.states['error']            = robot_status['error']
        self.states['category']         = k_robot_cleaning_category[robot_status['cleaning']['category']]
        self.states['mode']             = k_robot_cleaning_mode[robot_status['cleaning']['mode']]
        self.states['modifier']         = k_robot_cleaning_modifier[robot_status['cleaning']['modifier']]
        self.states['navigation']       = k_robot_cleaning_navigation[robot_status['cleaning']['navigationMode']]
        self.states['spot_height']      = robot_status['cleaning']['spotHeight']
        self.states['spot_width']       = robot_status['cleaning']['spotWidth']
        self.states['firmware']         = robot_status['meta']['firmware']
        self.states['model']            = robot_status['meta']['modelName']
        self.states['batteryLevel']     = robot_status['details']['charge']
        self.states['charging']         = robot_status['details']['isCharging']
        self.states['docked']           = robot_status['details']['isDocked']
        self.states['schedule_enabled'] = robot_status['details']['isScheduleEnabled']

        self.available_commands         = robot_status['availableCommands']

        # self.states['command_available_pause']  = robot_status['availableCommands']['pause']
        # self.states['command_available_resume'] = robot_status['availableCommands']['resume']
        # self.states['command_available_return'] = robot_status['availableCommands']['goToBase']
        # self.states['command_available_start']  = robot_status['availableCommands']['start']
        # self.states['command_available_stop']   = robot_status['availableCommands']['stop']
        # self.states['dock_seen']                = robot_status['details']['dockHasBeenSeen']

        self.device.updateStatesOnServer([{'key':key,'value':self.states[key]} for key in self.states])

        if robot_status['state'] == 2:
            stateImg = indigo.kStateImageSel.SensorOn
        elif robot_status['state'] in [0,4]:
            stateImg = indigo.kStateImageSel.SensorTripped
        else:
            stateImg = indigo.kStateImageSel.SensorOff
        self.device.updateStateImageOnServer(stateImg)

        self.next_update = time.time() + self.frequency

    #-------------------------------------------------------------------------------
    # properties
    #-------------------------------------------------------------------------------
    @property
    def name(self):
        return self.device.name

    #-------------------------------------------------------------------------------
    # action methods
    #-------------------------------------------------------------------------------
    def start_cleaning(self, props):
        if self.available_commands['start']:
            self.logger.info(u'"{}" start house cleaning'.format(self.name))
            self.robot.start_cleaning(mode=int(props['mode']), navigation_mode=int(props['navigation']), category=int(props['map']))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" start cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def start_spot_cleaning(self, props):
        if self.available_commands['start']:
            self.logger.info(u'"{}" start spot cleaning'.format(self.name))
            self.robot.start_spot_cleaning(spot_width=int(props['width']), spot_height=int(props['height']))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" start cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def pause_cleaning(self):
        if self.available_commands['pause']:
            self.logger.info(u'"{}" pause cleaning'.format(self.name))
            self.robot.pause_cleaning()
            self.requestStatus()
        else:
            self.logger.error(u'"{}" pause cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def resume_cleaning(self):
        if self.available_commands['resume']:
            self.logger.info(u'"{}" resume cleaning'.format(self.name))
            self.robot.pause_cleaning()
            self.requestStatus()
        else:
            self.logger.error(u'"{}" resume cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def stop_cleaning(self):
        if self.available_commands['stop']:
            self.logger.info(u'"{}" resume cleaning'.format(self.name))
            self.robot.stop_cleaning()
            self.requestStatus()
        else:
            self.logger.error(u'"{}" stop cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def send_to_base(self):
        if self.available_commands['goToBase']:
            self.logger.info(u'"{}" go to base'.format(self.name))
            self.robot.send_to_base()
            self.requestStatus()
        else:
            self.logger.error(u'"{}" go to base command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def locate(self):
        self.logger.info(u'"{}" locate'.format(self.name))
        self.robot.locate()
        self.requestStatus()

    #-------------------------------------------------------------------------------
    def enable_schedule(self):
        self.logger.info(u'"{}" enable schedule'.format(self.name))
        self.robot.enable_schedule()
        self.requestStatus()

    #-------------------------------------------------------------------------------
    def disable_schedule(self):
        self.logger.info(u'"{}" disable schedule'.format(self.name))
        self.robot.disable_schedule()
        self.requestStatus()

    #-------------------------------------------------------------------------------
    def get_schedule(self):
        self.logger.info(u'"{}" get schedule'.format(self.name))
        self.logger.info(u"{}".format(self.robot.get_schedule().text))

    #-------------------------------------------------------------------------------
    def get_general_info(self):
        self.logger.info(u'"{}" get general info'.format(self.name))
        self.logger.info(u"{}".format(self.robot.get_general_info().text))

    #-------------------------------------------------------------------------------
    def get_local_stats(self):
        self.logger.info(u'"{}" get local stats'.format(self.name))
        self.logger.info(u"{}".format(self.robot.get_local_stats().text))

    #-------------------------------------------------------------------------------
    def get_preferences(self):
        self.logger.info(u'"{}" get preferences'.format(self.name))
        self.logger.info(u"{}".format(self.robot.get_preferences().text))

    #-------------------------------------------------------------------------------
    def get_map_boundaries(self):
        self.logger.info(u'"{}" get map boundaries'.format(self.name))
        self.logger.info(u"{}".format(self.robot.get_map_boundaries().text))

    #-------------------------------------------------------------------------------
    def get_robot_info(self):
        self.logger.info(u'"{}" get robot info'.format(self.name))
        self.logger.info(u"{}".format(self.robot.get_robot_info().text))


################################################################################
# Utilities
################################################################################
def validateTextFieldNumber(rawInput, numType=float, zero=True, negative=True):
    try:
        num = numType(rawInput)
        if not zero:
            if num == 0: raise
        if not negative:
            if num < 0: raise
        return True
    except:
        return False
