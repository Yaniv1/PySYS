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
        




# defining a class SYSTEM that represents a system with a name and an ID. 
class SYSTEM:
    
    # constructor method that initializes the SYSTEM object with a name and an ID. If no name is provided, it defaults to an empty string. 
    # If no ID is provided, it generates a unique ID using the uuid module.
    # the constructor's first parameter is always self, which refers to the instance of the class being created. 
    # This allows us to access and modify the instance's attributes and methods within the class.
    def __init__(self, name="", id=str(uuid.uuid4())):
        self.name, self.id = name, id   

        # the constructor calls another method of the class which deactivates the system - we don't know how yet.
        # but this is a common pattern to separate concerns and behaviors - what vs how.
        self.deactivate()
                
    # a method that takes any number of keyword arguments and sets the corresponding attributes of the SYSTEM instance to the provided values.
    def get_input(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self,k,v)
            
    # a method that returns a dictionary containing the attributes of the SYSTEM instance.
    # if the attributes parameter is provided, it filters the output to include only those attributes; otherwise, it returns all attributes.
    def provide_output(self, attributes=[]):
        return {k:v for k,v in self.__dict__.items() if k in attributes or attributes==[]}
    

    # a method that activates the system by setting its state to 'ON', starting a new thread to run the system's main loop, and setting the _running attribute to True.
    def activate(self, do=[{"func":print, "args":[], "kwargs":{}}], cycle=1.0, cycles=10):        
        self.get_input(state='ON', _running=True, do=do, cycle=cycle, cycles=cycles)
        # a thread is created to run the system's main loop in the background.
        # a thread is a separate flow of execution that allows the program to perform multiple tasks concurrently. 
        # In this case, the thread will run the run() method of the SYSTEM class, which contains the main loop of the system.
        self.thread = threading.Thread(target=self.run, kwargs={"cycle": cycle, "cycles": cycles}, daemon=True)
        self.thread.start()       
        
    # a method that deactivates the system by setting its state to 'OFF' and setting the _running attribute to False, which will stop the main loop in the run() method.
    def deactivate(self):
        self.get_input(state='OFF', _running=False)
        
    # a method that runs the main loop of the system. 
    # It takes a list of functions to execute (do) and a cycle time (cycle) as parameters. The loop continues to run as long as the _running attribute is True.
    def run(self, cycle=1.0, cycles=10):
        self.cycle = cycle
        cycle_count = 0
        while getattr(self,'_running',False) and (cycle_count < cycles):
            # runs the loop as long as the _running attribute is True. 
            # The getattr() function is used to safely access the _running attribute, providing a default value of False if it doesn't exist.
            self.pclock = time.time()
            print(f"{self.name} running cycle {cycle_count+1}/{cycles} at{self.pclock} milliseconds with cycle time {cycle} seconds.")
            # execute each function in the do list, passing each function its own arguments and keyword arguments. 
            for f in getattr(self,'do',[{"func":print, "args":[], "kwargs":{}}]):
                r = f.get("func", print)(*f.get("args", []), **f.get("kwargs", {}))
                # if the return value of the function is a dictionary, it calls the get_input method to update the SYSTEM instance's attributes with the key-value pairs from the returned dictionary.
                if type(r) is dict:
                    self.get_input(**r)
                # the results of each step function are stored in the variable r, which can be used for further processing or analysis if needed.
            # the time.sleep() function is used to pause the execution of the loop for a duration calculated as the difference between the specified cycle time and the actual time taken for the current iteration of the loop.
            cycle_count+=1
            self.clock = time.time()
            elapsed = self.clock - self.pclock
            print(f"{elapsed=} idle={cycle - elapsed}")
            time.sleep(max(0, cycle - elapsed))


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
