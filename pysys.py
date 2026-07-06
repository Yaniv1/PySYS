import pandas as pd
import numpy as np
import datetime as dt
import os
import sys
import json
import threading
import time
import uuid


class THING:
    def __init__(self, name="", id=None, objects=None, processes=None):
        self.name = name
        self.id = id if id is not None else str(uuid.uuid4())
        self.OBJECTS = list(objects) if objects is not None else []
        self.PROCESSES = list(processes) if processes is not None else []

class OBJECT(THING):
    def __init__(self, name, id=None, states=None, objects=None, processes=None):
        super().__init__(name, id, objects, processes)
        self.STATES = list(states) if states is not None else []

class PROCESS(THING):
    def __init__(self, name, id=None, behavior=print, objects=None, processes=None):
        super().__init__(name, id, objects, processes)
        self.behavior = behavior  # default = print
    
    def RUN(self, *args, **kwargs):
        return self.behavior(*args, **kwargs)
        



# --------------------------
# Baseline Scenario
# --------------------------
def SCENARIO(   System, 
                Environment,
                name = "Baseline Aircraft Taxiing Scenario",
                steps = []):
    """
    Generic scenario:
    """
    
    print(name)
    
    for i, step in enumerate(steps, start=1):
        System, Environment = step(System, Environment)
        print(f"Step {i}: {result}")

    # Print final states
    print("\n=== Final States - Baseline Scenario ===")
    for obj in [System.aircraft, System.location, System.engine_power,
                System.motion, Environment.motion_command, Environment.sd1]:
        print(f"{obj.name:22}: {obj.STATES}")


# --------------------------
# Example usage
# --------------------------




class System:
    
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