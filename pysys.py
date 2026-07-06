import copy
import datetime as dt
import os
import sys
import json
import threading
import time
import uuid
import math
import random
import copy

class THING:
    def __init__(self, name="", id=None, objects=None, processes=None):
        self.name = name
        self.id = id if id is not None else str(uuid.uuid4())
        self.OBJECTS = list(objects) if objects is not None else []
        self.PROCESSES = list(processes) if processes is not None else []

class OBJECT(THING):
    def __init__(self, name, id=None, states=None, state=None, objects=None, processes=None):
        super().__init__(name, id, objects, processes)
        self.STATES = list(states) if states is not None else []
        self.state = state

class PROCESS(THING):
    def __init__(self, name, id=None, behavior=print, objects=None, processes=None):
        super().__init__(name, id, objects, processes)
        self.behavior = behavior  # default = print
    
    def RUN(self, *args, **kwargs):
        return self.behavior(*args, **kwargs)
        






class SYSTEM:
    
    def __init__(self, name="", id=str(uuid.uuid4())):
        self.name, self.id = name, id        
        self.deactivate()
                
    def get_input(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self,k,v)
            
    def provide_output(self, attributes=[]):
        return {k:v for k,v in self.__dict__.items() if k in attributes or attributes==[]}
    def activate(self):
        
        self.get_input(state='ON')        
        self._running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()       
        
    def deactivate(self):
        self.get_input(state='OFF')
        self._running = False        
        
    def run(self, do=[print], cycle=1.0):
        self.cycle = cycle
        while getattr(self,'_running',False):
            self.pclock = getattr(self,'clock',time.time())
            self.clock = time.time()
            self.interval = self.clock-self.pclock
            for f in do:
                f(self.__dict__)
            time.sleep(cycle-(time.time()-self.clock))



# --------------------------
# Baseline Scenario
# --------------------------
def SCENARIO(   System, 
                Environment,
                name = "Baseline Scenario",
                steps = []):
    """
    Generic scenario:
    """
    
    print(name)
    
    for i, step in enumerate(steps, start=1):
        System, Environment = step(System, Environment)
        print(f"Step {i}:")
        print(System.__dict__)
        print(Environment.__dict__)

    # Print final states
    print("\n=== Final States - Baseline Scenario ===")
    for obj in dir(System):
        if not(obj.startswith('__')):
            try:
                print(f"{obj.name:32}: {obj.STATES}")
            except AttributeError:
                print(f"{obj=}")


# --------------------------
# Example usage
# --------------------------
STATE_VAR = 'Number'
STATE_VAR_STATES = list(range(10))

def complement(System, Environment):
    
    new_env_state_idx = random.randint(0,len(STATE_VAR_STATES)-1)
    new_env_state = STATE_VAR_STATES[new_env_state_idx]
    env_state_var = copy.deepcopy(getattr(Environment, STATE_VAR))
    env_state_var.state = new_env_state
    setattr(Environment, STATE_VAR, env_state_var)

    new_sys_state = STATE_VAR_STATES[-new_env_state_idx]
    sys_state_var = copy.deepcopy(getattr(System, STATE_VAR))
    sys_state_var.state = new_sys_state
    setattr(System, STATE_VAR, sys_state_var)

    print("System state:", getattr(System, STATE_VAR).state)
    print("Environment state:", getattr(Environment, STATE_VAR).state)

    time.sleep(1)
    return System, Environment


if __name__ == "__main__":

    MySystem = SYSTEM('MY System',id='MySys')
    Environment = SYSTEM('Enviornemnt', id='Env')
    
    setattr(Environment, STATE_VAR, OBJECT(STATE_VAR, states=STATE_VAR_STATES))
    setattr(MySystem, STATE_VAR, OBJECT(STATE_VAR, states=STATE_VAR_STATES))

    MySystem.deactivate()
    Environment.deactivate()
    Environment.activate()
    MySystem.activate()

    SCENARIO(MySystem, Environment, name="Baseline Scenario", 
             steps=[complement for i in range(10)])


    # time.sleep(5)
    MySystem.deactivate()
    Environment.deactivate()
