# GENERIC INSTRUCTIONS


1. Build a python module that represents a system based on the attached Object Process Methodology model's formal specification in Object Process Language (OPL) as part of the HTML report of the model.
2. Use the building blocks in the pysys.py packages which is attached.
3. Create classes that inhreit from pysys.OBJECT for all the objects in the model before instantiating them as instances of their corresponding classes.
4. Capture model processes as behavior functions that use the @BEHAVIOR decorator.

4a. Create a SYSTEM instance for each top level systemic OBJECTs that exhibit PROCESSES and for each top level systemic PROCESS that is not owned by any object
4b. Create a SYSTEM instance for the ENVIORNMENT and include all the OBJECTS and PROCESSES that have environmenal affiliation.
4c. If an OBJECT is just an operand and has no processes, do not initially create a SYSTEM for it - only an OBJECT instance.

5. Create a PROCESS class for each model process and assign the behavior function as the BEHAVIOR of the PROCESS.
6. When an OBJECT exhibits a PROCESS - Append PROCESS instance to the METHODS list of the parent OBJECT instance of the object that owns (exhibits) the process in the model.
7. When an OBJECT exhibits an OBJECT - Append OBJECT instance to the ATTRIBUTES list of the parent OBJECT instance.
8. When an PROCESS exhibits an OBJECT - Append OBJECT instance to the ATTRIBUTES list of the parent PROCESS instance.
9. When an OBJECT consists of an OBJECT - Append OBJECT instance to the PARTS list of the parent PROCESS instance.
10.When an PROCESS consists of an PROCESS - Append OBJECT instance to the SUBPROCESSES list of the parent PROCESS instance.
11.When an OBJECT zooms into an OBJECT - Append OBJECT instance to the ORGANS list of the parent OBJECT instance.
12.When an PROCESS zooms into an OBJECT - Append OBJECT instance to the ORGANS list of the parent PROCESS instance.
13.When an OBJECT zooms into an PROCESS - Append PROCESS instance to the STEPS list of the parent OBJECT instance.
14.When an PROCESS zooms into an PROCESS - Append PROCESS instance to the STEPS list of the parentPROCESS instance.
15.When an OBJECT has STATES - Append STATE instances to the STATES list of the parent OBJECT instance.


16. Inheritence in the model: the parent model object is defined as a parent class that inherits from OBJECT, the child model object is defined as a child class that inherits from the parent class. each object gets instantiated from its class - parent or child.

17. all behavior functions consume the model and optionally context which modifies the behavior
18. all behavior functions store outputs back into the model. they can also emit outputs that don't go into the model for observability purposes.

General Instructions:
1. Follow only what is in the model - do not make anything up.
2. If something is missing in the model let me know - I will update the model and regenerate the specification. We don't want any behavior to be captured in the code if not previously captured in the model.
3. create a MODEL instance for the architecture, and include all the free objects and processes in the model. a free object is an object not owned by any other object. A free process is a process not owned by any object or not contained in another process.
4. Store all the domain structure in a single .py file.
5. Names of objects should be CamelCase and names of processes should be pep-8 compliant.
6. define constants  and variables from the model as OBJECT instances just like the rest of the objects. Then list constants and variables as objects under the object or process that owns them. for example Define an OBJECT class (e.g., class Distance(OBJECT): ...) and instantiate them inside their owning process (so they show up as sub-objects of Taxiing),
7. Store variables with units as tuples. Separate the numeric value for the units.
8. there is no need to prefix or suffix code blocks like classes or functions. for example the taxiing behavior can simply be called taxiing withouth behavior_ prefix or _behavior suffix.

Code Generation Mode:
1. In refine mode, build on the existing Python module supplied in the prompt. Preserve compatible code and resources, and change only what is required by the model or instructions.
2. In regenerate mode, ignore any existing Python module and create the outcome implementation from scratch.

Solution Creation Instuctions:
1. Always provide a direct entry point through a main() function that will be executed if the model file is excuted directly (using the conventional `if __name__=="__main__":` clause)
2. Always create the environmental system before you create the system of interest.
3. Provide an environment-owned input consumption function that will collect values for all the environmental entities.

Best Practices:
1. Create a readme.md file that describes the solution in its final shape.
2. Create a update.md file that describes what changed with each version. For new versions prepend version update summary at the top of the file:
```
# Version { %Y-%m-%d %H:%M:%S }
{ Version Summary - What changed from the previous version}
```