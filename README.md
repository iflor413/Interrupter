This module contains 4 types of limiters that are capable
of interrupting a function according to its RAM usage,
computational time, active threads or active processes,
through the use of a wrapper.  

The module provides wrappers that runs a function in a
parent process along side two threads, this group of
threads are known as the Interrupter, which monitors,
communicates and initiates the safe termination of the
parent process, its child processes/threads and nested
threads (Note: **THIS EXCLUDES NESTED CHILD PROCESSES**).  

The controlled termination of the parent process results in
the freeing of all resources used in the parent process,
including resources used by the wrapped function. Any and
all errors are caught and raised in the main process after
safely termiating the parent process.  

Communication between the current process and the parent
process are based on the use of Event and SimpleQueue pipes,
therefore, information flow from the wrapped function to the
current process is limited, potentially causing a bottleneck.  

The main application for this wrapper is for stability testing.  

Furthermore, this application has customization support, allowing
for the monitoring of different factors (see the Custom section
for more information).

**Python:** 3.3, 3.4, 3.5, 3.6, 3.7, 3.8  

## Note:
**The Interrupter is NOT capable of safely**
**terminating nested processes in the child processes**
**of the parent process in the Interrupter. THIS**
**LIMITATION ALSO APPLIES TO NESTED INTERRUPTERS.**

On the other hand, nested threads can be used
safely in the parent process of the Interrupter,
however, the Interrupter cannot catch any errors
raised inside those threads.

This warning also applies to custom cond_fn,
and ternimation_fn as they run in child threads
in the parent process of the Interrupter.

**WARNING: Only use nested processes if you know**
**what you are doing as these nested processes will**
**become orphaned if not terminated by the user**
**properly.**

## Custom:
```
>>> from interrupt import interrupter
>>> 
>>> #operator is an optional **kwarg
>>> def condition_fn(limit, operator=...):
>>>     if condition(limit):
>>>         raise ...
>>> 
>>> def wrapper(limit, **kwargs):
>>>     '''
>>>         When operator is None, then the condition_fn
>>>         is used to define the operator if at all. If
>>>         is a method then it will be called at the
>>>         initialization of the parent process, value
>>>         is then passed to the condition_fn.
>>>     '''
>>>     return interrupt(condition_fn, limit, operator=..., **kwargs)
```

## Example use of limiters:
**RAM Limit:**
```
>>> from interrupt import RAM_limit
>>> import traceback
>>>
>>> try:
>>>     @RAM_limit(100) #in KB
>>>     def foo():
>>>         a = 'a'*2**20 #~1MB
>>>         return a
>>>     
>>>     foo()
>>> except:
>>>     traceback.print_exc()
```

**Time Limit:**
```
>>> from interrupt import time_limit
>>> from itertools import count
>>> import traceback
>>> 
>>> try:
>>>     @time_limit(2)
>>>     def foo():
>>>         counter = count()
>>>         
>>>         for _ in range(5):
>>>             print(next(counter))
>>>             time.sleep(1)
>>>         return a
>>>     
>>>     foo()
>>> except:
>>>     traceback.print_exc()
```

**Thread Limit:**
```
>>> from interrupt import thread_limit
>>> from itertools import count
>>> import traceback
>>> 
>>> try:
>>>     def foo():
>>>         counter = count()
>>>         
>>>         for _ in range(5):
>>>             print(next(counter))
>>>             time.sleep(1)
>>>     
>>>     @thread_limit(0)
>>>     def foo():
>>>         thread = Thread(target=foo)
>>>         thread.start()
>>>         thread.join()
>>>     
>>>     foo()
>>> except:
>>>     traceback.print_exc()
```

**Process Limit:**
```
>>> from interrupt import process_limit
>>> from itertools import count
>>> import traceback
>>> 
>>> try:
>>>     def foo():
>>>         counter = count()
>>>         
>>>         for _ in range(5):
>>>             print(next(counter))
>>>             time.sleep(1)
>>>     
>>>     @process_limit(0)
>>>     def foo():
>>>         process = Process(target=foo)
>>>         process.start()
>>>         process.join()
>>>     
>>>     foo()
>>> except:
>>>     traceback.print_exc()
```

