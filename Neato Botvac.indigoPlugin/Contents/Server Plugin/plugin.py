#! /usr/bin/env python
# -*- coding: utf-8 -*-
################################################################################

import indigo

import threading
import queue
import time
import json
from requests import RequestException

try:
    from pybotvac import Account, Neato, PasswordSession
    from pybotvac import Robot
    from pybotvac.exceptions import NeatoException
except:
    indigo.server.log("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!", isError=True)
    indigo.server.log("pybotvac library must now be manually installed from terminal:", isError=True)
    indigo.server.log("    pip3 install pybotvac", isError=True)
    indigo.server.log("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!", isError=True)
    

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
    15: 'suspended_exploration',
    }
k_robot_cleaning_category = {
    0:  'none',
    1:  'manual',
    2:  'house',
    3:  'spot',
    4:  'room',
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

RETRY_CONNECTION_MINUTES = 15

################################################################################
class Plugin(indigo.PluginBase):

    #-------------------------------------------------------------------------------
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        self.account = None
        self.connected = False
        self.instance_dict = dict()

    #-------------------------------------------------------------------------------
    # start, stop and plugin config
    #-------------------------------------------------------------------------------
    def startup(self):
        self.debug = self.pluginPrefs.get('showDebugInfo',False)
        if self.debug:
            self.logger.debug('Debug logging enabled')

        self.updateAccount()

    #-------------------------------------------------------------------------------
    def shutdown(self):
        self.pluginPrefs['showDebugInfo'] = self.debug

    #-------------------------------------------------------------------------------
    def validatePrefsConfigUi(self, valuesDict):
        errorsDict = indigo.Dict()

        for key in ['email','password']:
            if not valuesDict.get(key,''):
                errorsDict[key] = 'Required'

        if len(errorsDict) > 0:
            self.logger.debug(f'validate plugin config error: \n{errorsDict}')
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            self.updateAccount()
            self.debug = valuesDict.get('showDebugInfo',False)
            if self.debug:
                self.logger.debug('Debug logging enabled')

    #-------------------------------------------------------------------------------
    def runConcurrentThread(self):
        next_connection = time.time() + RETRY_CONNECTION_MINUTES*60
        try:
            while True:
                loop_time = time.time()
                for instance in self.instance_dict.values():
                    instance.task(instance.tick)
                if not self.connected:
                    if loop_time > next_connection:
                        self.updateAccount()
                        next_connection = loop_time + RETRY_CONNECTION_MINUTES*60
                self.sleep(5)
        except self.StopThread:
            pass

    #-------------------------------------------------------------------------------
    # menu methods
    #-------------------------------------------------------------------------------
    def updateAccount(self):
        self.connected = False
        email = self.pluginPrefs.get('email','')
        password = self.pluginPrefs.get('password','')
        if email and password:
            try:
                password_session = PasswordSession(email=email, password=password, vendor=Neato())
                self.account = Account(password_session)
                robots = self.account.robots
                self.connected = True
                self.logger.info('Neato account updated')
                if len(robots) > 0:
                    self.logger.info('Robots found:')
                    for robot in self.account.robots:
                        self.logger.info(f'     {robot.name} ({robot.serial})')
                else:
                    self.logger.error('No robots found')
            except Exception as e:
                self.logger.error('Error accessing Neato account - check plugin config and internet connection')
                self.logger.debug(str(e))
        else:
            # plugin is not configured
            self.logger.error('No account credentials - check plugin config')

    #-------------------------------------------------------------------------------
    def getRobotInstance(self, serial):
        if self.connected:
            for robot in self.account.robots:
                if serial == robot.serial:
                    return robot
        return None

    #-------------------------------------------------------------------------------
    def accountConnected(self):
        return self.connected

    #-------------------------------------------------------------------------------
    def toggleDebug(self):
        if self.debug:
            self.logger.debug('Debug logging disabled')
            self.debug = False
        else:
            self.debug = True
            self.logger.debug('Debug logging enabled')

    #-------------------------------------------------------------------------------
    # device methods
    #-------------------------------------------------------------------------------
    def deviceStartComm(self, dev):
        if dev.configured:
            if not dev.version or ver(dev.version) < ver(self.pluginVersion):
                props = dev.pluginProps
                props['version'] = self.pluginVersion
                dev.replacePluginPropsOnServer(props)
                dev.stateListOrDisplayStateIdChanged()
            self.instance_dict[dev.id] = Botvac(dev, self.getRobotInstance, self.logger)


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
            errorsDict['serial'] = 'Required'
        else:
            for robot in self.account.robots:
                if valuesDict['serial'] == robot.serial:
                    # valuesDict['secret'] = robot.secret
                    valuesDict['traits'] = robot.traits
                    valuesDict['name'] = robot.name
                    valuesDict['address'] = robot.serial
                    break
            else:
                errorsDict['serial'] = 'Robot not found.  Update account and try again.'

        if len(errorsDict) > 0:
            self.logger.debug('validate device config error: \n{errorsDict}')
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
                return[('**Account Offline**',0)]

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
            self.logger.debug(f'validate action config error: \n{errorsDict}')
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    #-------------------------------------------------------------------------------
    # action control
    #-------------------------------------------------------------------------------
    def actionControlUniversal(self, action, dev):
        instance = self.instance_dict[dev.id]

        # STATUS REQUEST
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.logger.info(f'"{dev.name}" status update')
            instance.task(instance.request_status)
        # UNKNOWN
        else:
            self.logger.debug(f'"{dev.name}" {action.deviceAction} request ignored')

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

    #-------------------------------------------------------------------------------
    def __init__(self, device, getRobotInstance, logger):
        super(Botvac, self).__init__()
        self.daemon     = True
        self.cancelled  = False
        self.queue      = queue.Queue()

        self.getRobot = getRobotInstance
        self.logger = logger

        self.device = device
        self.props  = device.pluginProps
        self.serial = self.props.get('serial','')
        self.frequency_idle = int(self.props.get('statusFrequency','300'))
        self.frequency_busy = int(self.props.get('statusFrequencyBusy',self.frequency_idle))

        self.states = {
            'state'            : k_robot_state[0],
            'action'           : k_robot_action[0],
            'error'            : '',
            'category'         : 0,
            'mode'             : 1,
            'modifier'         : 1,
            'navigation'       : 1,
            'spot_height'      : 0,
            'spot_width'       : 0,
            'firmware'         : '',
            'model'            : '',
            'batteryLevel'     : 0,
            'charging'         : False,
            'docked'           : False,
            'dock_seen'        : False,
            'schedule_enabled' : False,
            'connected'        : False,
            'display'          : 'offline',
            }
        self.available_commands = dict()
        self.next_update = 0
        self.error = False

        self.task(self.request_status)
        self.start()

    #-------------------------------------------------------------------------------
    def run(self):
        self.logger.debug(f'"{self.name}" thread started')
        while not self.cancelled:
            try:
                func, args = self.queue.get(True,2)
                try:
                    func(*args)
                except NotImplementedError:
                    self.logger.error(f'"{self.name}" task "{func.__name__}" not implemented')
                self.queue.task_done()
            except queue.Empty:
                pass
            except Exception as e:
                self.logger.exception(f'"{self.name}" thread error \n{e}')
        else:
            self.logger.debug(f'"{self.name}" thread cancelled')

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
            self.request_status()

    #-------------------------------------------------------------------------------
    def request_status(self):
        self.logger.info(f'"{self.name}" request status')
        robot_status = {}

        self.robot = self.getRobot(self.serial)
        if not self.robot:
            self.device.setErrorStateOnServer('offline')
            self.error = True
            self.logger.error(f'"{self.name}" offline')
            self.available_commands = {}
        else:
            if self.error:
                self.device.setErrorStateOnServer(None)
                self.error = False
                self.logger.info(f'"{self.name}" online')

            try:
                robot_status = self.robot.state

                self.states['state']            = k_robot_state[robot_status.get('state',0)]
                self.states['action']           = k_robot_action[robot_status.get('action',0)]
                self.states['error']            = robot_status.get('error','') if self.states['state']=='error' else ''
                self.states['room']             = robot_status.get('cleaning',{}).get('boundary',{}).get('name','')
                self.states['category']         = k_robot_cleaning_category[robot_status.get('cleaning',{}).get('category',0)]
                self.states['mode']             = k_robot_cleaning_mode[robot_status.get('cleaning',{}).get('mode',1)]
                self.states['modifier']         = k_robot_cleaning_modifier[robot_status.get('cleaning',{}).get('modifier',1)]
                self.states['navigation']       = k_robot_cleaning_navigation[robot_status.get('cleaning',{}).get('navigationMode',1)]
                self.states['spot_height']      = robot_status.get('cleaning',{}).get('spotHeight',0)
                self.states['spot_width']       = robot_status.get('cleaning',{}).get('spotWidth',0)
                self.states['firmware']         = robot_status.get('meta',{}).get('firmware','')
                self.states['model']            = robot_status.get('meta',{}).get('modelName','')
                self.states['batteryLevel']     = robot_status.get('details',{}).get('charge',0)
                self.states['charging']         = robot_status.get('details',{}).get('isCharging',False)
                self.states['docked']           = robot_status.get('details',{}).get('isDocked',False)
                self.states['dock_seen']        = robot_status.get('details',{}).get('dockHasBeenSeen',False)
                self.states['schedule_enabled'] = robot_status.get('details',{}).get('isScheduleEnabled',False)
                self.available_commands         = robot_status.get('availableCommands',{})

                self.logger.debug(f'"{self.name}" available commands: {self.available_commands}')

                self.states['connected'] = True

            except NeatoException as e:
                self.logger.error(f'{e}')
                self.logger.info(f'"{self.name}" offline')
                self.states['connected'] = False
            except KeyError:
                self.logger.error(f'"{self.name}" received unexpected status message')
                self.logger.debug(f'{json.dumps(robot_status, sort_keys=True, indent=4)}')
                self.states['connected'] = False

            if self.states['category'] == 'room' and not self.states['room']:
                self.states['category'] = 'house'

            if self.states['connected'] == False:
                self.states['display'] = 'offline'
                self.next_update = time.time() + self.frequency_idle
            elif self.states['state'] == 'busy':
                self.states['display'] = self.states['action']
                self.next_update = time.time() + self.frequency_busy
            else:
                self.states['display'] = self.states['state']
                self.next_update = time.time() + self.frequency_idle
            self.states['display'] = self.states['display'].replace('_',' ')

            if self.states['state'] in ['invalid','error'] or self.states['connected'] == False:
                stateImg = indigo.kStateImageSel.SensorTripped
            elif self.states['state'] == 'busy':
                stateImg = indigo.kStateImageSel.SensorOn
            else: # idle, paused
                stateImg = indigo.kStateImageSel.SensorOff

            self.device.updateStatesOnServer([{'key':key,'value':self.states[key]} for key in self.states])
            self.device.updateStateImageOnServer(stateImg)

        self.logger.debug(f'"{self.name}" status update complete')

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
        if self.available_commands.get('start',False) and self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" start house cleaning')
                self.robot.start_cleaning(mode=int(props['mode']), navigation_mode=int(props['navigation']), category=int(props['map']))
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" start cleaning command not currently available')

    #-------------------------------------------------------------------------------
    def start_spot_cleaning(self, props):
        if self.available_commands.get('start',False) and self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" start spot cleaning')
                self.robot.start_spot_cleaning(spot_width=int(props['width']), spot_height=int(props['height']))
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" start cleaning command not currently available')

    #-------------------------------------------------------------------------------
    def pause_cleaning(self):
        if self.available_commands.get('pause',False) and self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" pause cleaning')
                self.robot.pause_cleaning()
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" pause cleaning command not currently available')

    #-------------------------------------------------------------------------------
    def resume_cleaning(self):
        if self.available_commands.get('resume',False) and self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" resume cleaning')
                self.robot.resume_cleaning()
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" resume cleaning command not currently available')

    #-------------------------------------------------------------------------------
    def stop_cleaning(self):
        if self.available_commands.get('stop',False) and self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" stop cleaning')
                self.robot.stop_cleaning()
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" stop cleaning command not currently available')

    #-------------------------------------------------------------------------------
    def send_to_base(self):
        if self.available_commands.get('goToBase',False) and self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" go to base')
                self.robot.send_to_base()
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" go to base command not currently available')

    #-------------------------------------------------------------------------------
    def locate(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" locate')
                self.robot.locate()
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" locate command not currently available')

    #-------------------------------------------------------------------------------
    def enable_schedule(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" enable schedule')
                self.robot.enable_schedule()
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" enable schedule command not currently available')

    #-------------------------------------------------------------------------------
    def disable_schedule(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" disable schedule')
                self.robot.disable_schedule()
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
            self.request_status()
        else:
            self.logger.error(f'"{self.name}" disable schedule command not currently available')

    #-------------------------------------------------------------------------------
    def get_schedule(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" get schedule')
                result_dict = self.robot.get_schedule().json()
                self.logger.info(f"{json.dumps(result_dict, sort_keys=True, indent=4)}")
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
                self.request_status()
        else:
            self.logger.error(f'"{self.name}" get schedule command not currently available')

    #-------------------------------------------------------------------------------
    def get_general_info(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" get general info')
                result_dict = self.robot.get_general_info().json()
                self.logger.info(f"{json.dumps(result_dict, sort_keys=True, indent=4)}")
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
                self.request_status()
        else:
            self.logger.error(f'"{self.name}" get general info command not currently available')

    #-------------------------------------------------------------------------------
    def get_local_stats(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" get local stats')
                result_dict = self.robot.get_local_stats().json()
                self.logger.info(f"{json.dumps(result_dict, sort_keys=True, indent=4)}")
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
                self.request_status()
        else:
            self.logger.error(f'"{self.name}" get local stats command not currently available')

    #-------------------------------------------------------------------------------
    def get_preferences(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" get preferences')
                result_dict = self.robot.get_preferences().json()
                self.logger.info(f"{json.dumps(result_dict, sort_keys=True, indent=4)}")
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
                self.request_status()
        else:
            self.logger.error(f'"{self.name}" get preferences command not currently available')

    #-------------------------------------------------------------------------------
    def get_map_boundaries(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" get map boundaries')
                result_dict = self.robot.get_map_boundaries().json()
                self.logger.info(f"{json.dumps(result_dict, sort_keys=True, indent=4)}")
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
                self.request_status()
        else:
            self.logger.error(f'"{self.name}" get map boundaries command not currently available')

    #-------------------------------------------------------------------------------
    def get_robot_info(self):
        if self.states['connected']:
            try:
                self.logger.info(f'"{self.name}" get robot info')
                result_dict = self.robot.get_robot_info().json()
                self.logger.info(f"{json.dumps(result_dict, sort_keys=True, indent=4)}")
            except RequestException:
                self.logger.error(f'"{self.name}" communication error')
                self.request_status()
        else:
            self.logger.error(f'"{self.name}" get robot info command not currently available')


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


#-------------------------------------------------------------------------------
def ver(vstr): return tuple(map(int, (vstr.split('.'))))
