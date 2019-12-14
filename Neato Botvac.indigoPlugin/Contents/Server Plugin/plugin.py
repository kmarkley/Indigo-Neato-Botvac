#! /usr/bin/env python
# -*- coding: utf-8 -*-
################################################################################

import indigo

import threading
import Queue
import time
import json

from pybotvac import Account
from pybotvac import Robot

from requests import RequestException

################################################################################
# globals
k_robot_state = {
    0:  'invalid',
    1:  'idle',
    2:  'busy',
    3:  'paused',
    4:  'error'
    }
k_robot_action = {
    0:  'none',
    1:  'house_cleaning',
    2:  'spot_cleaning',
    3:  'manual_cleaning',
    4:  'docking',
    5:  'user_menu_active',
    6:  'suspended_cleaning',
    7:  'updating',
    8:  'copying_logs',
    9:  'recovering_location',
    10: 'iec_test',
    11: 'map_cleaning',
    12: 'exploring_map',
    13: 'acquiring_persistent_maps',
    14: 'creating_uploading_map',
    15: 'suspended_exploration'
    }
k_robot_cleaning_category = {
    0:  'none',
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
        self.instance_dict = dict()

    #-------------------------------------------------------------------------------
    # start, stop and plugin config
    #-------------------------------------------------------------------------------
    def startup(self):
        self.debug = self.pluginPrefs.get('showDebugInfo',False)
        if self.debug:
            self.logger.debug(u'Debug logging enabled')

        self.updateAccount()

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
    # menu methods
    #-------------------------------------------------------------------------------
    def updateAccount(self):
        email = self.pluginPrefs.get('email','')
        password = self.pluginPrefs.get('password','')

        if email and password:
            try:
                self.account = Account(email, password)
                robots = self.account.robots
                self.logger.info(u'Neato account updated')
                if len(robots) > 0:
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
            # dev.stateListOrDisplayStateIdChanged()
            for robot in self.account.robots:
                if dev.pluginProps['serial'] == robot.serial:
                    secret = robot.secret
                    break
            if dev.deviceTypeId == 'NeatoBotvac':
                self.instance_dict[dev.id] = Botvac(dev, secret, self.logger)

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
                    # valuesDict['secret'] = robot.secret
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
        try:
            return [(robot.serial,robot.name) for robot in self.account.robots]
        except:
            if targetId != 0:
                return[(self.instance_dict(targetId).props['name'],self.instance_dict(targetId).props['serial'])]
            else:
                return[(u'**Account Offline**',0)]

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
    def __init__(self, device, secret, logger):
        super(Botvac, self).__init__()
        self.daemon     = True
        self.cancelled  = False
        self.queue      = Queue.Queue()

        self.logger = logger

        self.device = device
        self.props  = device.pluginProps

        self.frequency = int(self.props.get('statusFrequency','300'))

        self.states = dict()
        self.available_commands = dict()
        self.next_update = 0

        try:
            self.robot = Robot(self.props['serial'], secret, self.props['traits'], self.props['name'])
        except Exception as e:
            self.logger.error(u'"{}" initialization error.  Try updating Neato account from plugin menu.'.format(self.name))

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
                    self.logger.error(u'"{}" task "{}" not implemented'.format(self.name,func.__name__))
                self.queue.task_done()
            except Queue.Empty:
                pass
            except Exception as e:
                self.logger.exception(u'"{}" thread error \n{}'.format(self.name, e))
        else:
            self.logger.debug(u'"{}" thread cancelled'.format(self.name))

    #-------------------------------------------------------------------------------
    def task(self, func, *args):
        self.queue.put((func, args))
        # func(*args)

    #-------------------------------------------------------------------------------
    def cancel(self):
        self.cancelled = True

    #-------------------------------------------------------------------------------
    def tick(self):
        if time.time() >= self.next_update:
            self.requestStatus()

    #-------------------------------------------------------------------------------
    def requestStatus(self):
        self.logger.info(u'"{}" request status'.format(self.name))
        self.next_update = time.time() + self.frequency
        robot_status = u''
        try:
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
            self.states['dock_seen']        = robot_status['details']['dockHasBeenSeen']
            self.states['schedule_enabled'] = robot_status['details']['isScheduleEnabled']
            self.available_commands         = robot_status['availableCommands']

            self.states['connected']        = True

        except RequestException:
            self.logger.info(u'"{}" offline'.format(self.name))
            self.states['connected'] = False
        except KeyError:
            self.logger.error(u'"{}" received malformed status message'.format(self.name))
            self.logger.debug(u'{}'.format(json.dumps(robot_status, sort_keys=True, indent=4)))

        if self.states['connected'] == False:
            self.states['display'] = 'offline'
        elif self.states['state'] == 'busy':
            self.states['display'] = self.states['action']
        else:
            self.states['display'] = self.states['state']
        self.states['display'] = self.states['display'].replace('_',' ')

        if self.states['state'] in ['invalid','error'] or self.states['connected'] == False:
            stateImg = indigo.kStateImageSel.SensorTripped
        elif self.states['state'] == 'busy':
            stateImg = indigo.kStateImageSel.SensorOn
        else: # idle, paused
            stateImg = indigo.kStateImageSel.SensorOff

        self.device.updateStatesOnServer([{'key':key,'value':self.states[key]} for key in self.states])
        self.device.updateStateImageOnServer(stateImg)

        self.logger.debug(u'"{}" status update complete'.format(self.name))

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
        if self.available_commands['start'] and self.states['connected']:
            try:
                self.logger.info(u'"{}" start house cleaning'.format(self.name))
                self.robot.start_cleaning(mode=int(props['mode']), navigation_mode=int(props['navigation']), category=int(props['map']))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" start cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def start_spot_cleaning(self, props):
        if self.available_commands['start'] and self.states['connected']:
            try:
                self.logger.info(u'"{}" start spot cleaning'.format(self.name))
                self.robot.start_spot_cleaning(spot_width=int(props['width']), spot_height=int(props['height']))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" start cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def pause_cleaning(self):
        if self.available_commands['pause'] and self.states['connected']:
            try:
                self.logger.info(u'"{}" pause cleaning'.format(self.name))
                self.robot.pause_cleaning()
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" pause cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def resume_cleaning(self):
        if self.available_commands['resume'] and self.states['connected']:
            try:
                self.logger.info(u'"{}" resume cleaning'.format(self.name))
                self.robot.resume_cleaning()
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" resume cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def stop_cleaning(self):
        if self.available_commands['stop'] and self.states['connected']:
            try:
                self.logger.info(u'"{}" resume cleaning'.format(self.name))
                self.robot.stop_cleaning()
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" stop cleaning command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def send_to_base(self):
        if self.available_commands['goToBase'] and self.states['connected']:
            try:
                self.logger.info(u'"{}" go to base'.format(self.name))
                self.robot.send_to_base()
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" go to base command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def locate(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" locate'.format(self.name))
                self.robot.locate()
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" locate command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def enable_schedule(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" enable schedule'.format(self.name))
                self.robot.enable_schedule()
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" enable schedule command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def disable_schedule(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" disable schedule'.format(self.name))
                self.robot.disable_schedule()
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
            self.requestStatus()
        else:
            self.logger.error(u'"{}" disable schedule command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def get_schedule(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" get schedule'.format(self.name))
                result_dict = self.robot.get_schedule().json()
                self.logger.info(u"{}".format(json.dumps(result_dict, sort_keys=True, indent=4)))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
                self.requestStatus()
        else:
            self.logger.error(u'"{}" get schedule command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def get_general_info(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" get general info'.format(self.name))
                result_dict = self.robot.get_general_info().json()
                self.logger.info(u"{}".format(json.dumps(result_dict, sort_keys=True, indent=4)))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
                self.requestStatus()
        else:
            self.logger.error(u'"{}" get general info command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def get_local_stats(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" get local stats'.format(self.name))
                result_dict = self.robot.get_local_stats().json()
                self.logger.info(u"{}".format(json.dumps(result_dict, sort_keys=True, indent=4)))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
                self.requestStatus()
        else:
            self.logger.error(u'"{}" get local stats command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def get_preferences(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" get preferences'.format(self.name))
                result_dict = self.robot.get_preferences().json()
                self.logger.info(u"{}".format(json.dumps(result_dict, sort_keys=True, indent=4)))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
                self.requestStatus()
        else:
            self.logger.error(u'"{}" get preferences command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def get_map_boundaries(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" get map boundaries'.format(self.name))
                result_dict = self.robot.get_map_boundaries().json()
                self.logger.info(u"{}".format(json.dumps(result_dict, sort_keys=True, indent=4)))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
                self.requestStatus()
        else:
            self.logger.error(u'"{}" get map boundaries command not currently available'.format(self.name))

    #-------------------------------------------------------------------------------
    def get_robot_info(self):
        if self.states['connected']:
            try:
                self.logger.info(u'"{}" get robot info'.format(self.name))
                result_dict = self.robot.get_robot_info().json()
                self.logger.info(u"{}".format(json.dumps(result_dict, sort_keys=True, indent=4)))
            except RequestException:
                self.logger.error(u'"{}" communication error'.format(self.name))
                self.requestStatus()
        else:
            self.logger.error(u'"{}" get robot info command not currently available'.format(self.name))


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
