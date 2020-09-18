'''
    This module contains 4 types of limiters that are capable
    of interrupting a function according to its RAM usage,
    computational time, active threads or active processes,
    through the use of a wrapper.
    
    This module does this by
    running the wrapped function in a parent process along
    side two threads, this group is known as the Interrupter
    that monitors, communicates and initiates the safe
    termination of the parent process, its child
    processes/threads and nested threads (Note: **THIS EXCLUDES
    NESTED CHILD PROCESSES**).
    
    The controlled termination of
    the parent process results in the freeing of all resources
    used in the parent process, including resources used by the
    wrapped function. Any and all errors are caught and raised
    in the main process after safely termiating the parent
    process.
    
    Communication between the current process and the
    parent process are based on the use of Event and SimpleQueue
    pipes, therefore, information flow from the wrapped function
    to the current process is limited, potentially causing a
    bottleneck.
    
    The main application for this wrapper is for
    stability testing. Furthermore, this application has customization
    support, allowing for the monitoring of different factors
    (see the Custom section for more information).
    
Note:
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
Architechture:
/===========Current Process===========|=================Interrupter=================\
v                                     v                                             v
          callback(*cb_args, **cb_kwargs)
                       |                        cond_fn(limit, operator=None) <->--\
       /------------------------------\                    ^   |                   |
       |return/raise                  |                    |   v                   |
       |result                        |        /=====> Monitor Thread ----->\      |
       v           @wrapper           |        ^                            v      |
Current Process -------------> Parent Process -+>----> Function ------------+-<->--/
                                      ^        v                            v
                                      |        \>====> Termination Thread <-/
                                      |                        |
                                      \------------------------/
                                                    |
                                       trm_fn(*trm_args, *trm_kwargs)
'''

from multiprocessing import Process, Event, SimpleQueue, active_children
from threading import Thread, Event as _TEvent, active_count
from multiprocessing.synchronize import Event as _MEvent
from types import FunctionType, BuiltinMethodType
from functools import wraps

import traceback
import resource
import time
import sys

class IProcess(Process):
    '''
        This is a modified version of a
        Process that can use an Event to
        trigger the timeout when joining
        (Event can be from the threading
        or multiprocessing library).
        
        see multiprocessing.Process class
    '''
    def join(self, timeout=None):
        '''
            Arguments:
                *timeout    : Can now be triggered
                            by an event.
            
            see multiprocessing.Process.join method
        '''
        if isinstance(timeout, (_MEvent, _TEvent)):
            timeout.wait()
            timeout = 0
        
        super(Process, self).join(timeout=timeout)

def _format_tb(etype, value, tb, in_main=False):
    return (etype, traceback.format_exception(etype, value, tb), in_main)

def _raise_tb_stack(errors):
    stacked_tb = []
    last_etype = Exception
    for error in errors:
        etype, str_tb, in_main = error
        last_etype = etype
        
        str_tb+=['\nDuring monitoring of the Interrupter, '+
                        'the exception above occured.\n']*in_main
        
        stacked_tb.append(str_tb)
    
    _message = '\n'
    _message+='='*70+'\n'
    _message+=('\nDuring handling of the above exception, '+
            'another exception occurred:\n\n').join(
            [''.join(tb) for tb in stacked_tb])
    _message+='='*70
    
    raise last_etype(_message)

def interrupter(cond_fn, limit, operator=None, refresh_rate=None, daemon=None,
            trm_fn=None, trm_args=(), trm_kwargs={},
            callback=None, cb_args=(), cb_kwargs={}):
    '''
        This wrapper allows for the interruption
        or termination of a function as it is
        running and release all resources used
        for that function and in the Interrupter.
        This is accomplished through the use of
        a monitor with a 'limit' that will result
        in an exception once a condition is met.
        
        Condition function example:
        
            #operator is an optinal **kwarg
            def condition(limit, operator=...):
                if condition(limit):
                    raise ...
        
        Arguments:
            *cond_fn        : Is a function that will be used
                            to raise an exception as per condition
                            regarding the 'limit' and 'operator'.
                            
            *limit          : Is an arbitrary value defined by
                            the 'cond_fn 'used to determine
                            the rasing of an exception.
                            
            *operator       : Is an object that can be used in
                            the 'cond_fn', if supported. If
                            None, then it is defined by the 'cond_fn'
                            if avaiable. If is a method then it will
                            be called at the initialization of the
                            parent process.
                            
            *refresh_rate   : Is the number of times the monitor
                            will check the current environment
                            per second. If None, then it is
                            continous.
                            
            *daemon         : When True, uses a daemon Process
                            to run the decorated function.
                            
            *trm_fn         : Allows for the calling of a function
                            prior to the termination of the parent
                            process and its children inside the
                            parent process.('*trm_args', '**trm_kwargs'
                            are its arguments)
                            
            *callback       : Allows for a callback function to
                            be called once the parent process has
                            been terminated. ('*cb_args', '**cb_kwargs'
                            are its arguments)
                            
            returns result
            
            If raises an exception, then the error
            type will be the last exception caught
            showing a history of caught exceptions.
    '''
    def monitor(limit, pre_terminate, pre_conn, cond_kwargs):
        #catch errors raised by the cond_fn
        try:
            wait = (1/refresh_rate
                    if refresh_rate is not None and
                    isinstance(refresh_rate, (int, float)) and
                    refresh_rate > 0 else
                    0)
            
            while not pre_terminate.is_set():
                cond_fn(limit, **cond_kwargs)
                time.sleep(wait)
        except:
            pre_terminate.set()
            pre_conn.put(((_format_tb(*sys.exc_info(), in_main=True),), True))
    
    def termination(pre_terminate, terminate, pre_conn, conn):
        pre_terminate.wait()
        
        #Get results/errors
        result, exception = pre_conn.get() 
        
        #catch errors raised by the trm_fn
        try:
            if trm_fn is not None:
                trm_fn(*trm_args, **trm_kwargs)
        except:
            if exception:
                result += (_format_tb(*sys.exc_info(), in_main=True),)
            else:
                result, exception = (_format_tb(*sys.exc_info(), in_main=True),), True
        
        conn.put((result, exception))
        
        #TODO Identify nested processes for termination
        
        #termination of child processes in parent process
        for child in active_children(): 
            child.join(0)
            while child.is_alive():
                child.terminate()
        
        #signal for termination of parent process in the current process
        terminate.set() 
    
    def Main(terminate, conn, func, args, kwargs):
        pre_terminate = Event()
        pre_conn = SimpleQueue()
        
        termination_thread = Thread(target=termination,
            args=(pre_terminate, terminate, pre_conn, conn))
        
        cond_kwargs = {}
        
        #catch errors raised by the operator if a method
        try:
            if operator is not None:
                cond_kwargs = {'operator': (operator()
                    if isinstance(operator, (FunctionType, BuiltinMethodType)) else
                    operator)}
        except:
            pre_terminate.set()
            pre_conn.put(((_format_tb(*sys.exc_info(), in_main=True),), True))
        
        monitor_thread = Thread(target=monitor,
            args=(limit, pre_terminate, pre_conn, cond_kwargs))
        
        termination_thread.start()
        monitor_thread.start()
        
        #catch errors raised by the cond_fn
        try:
            result, exception = func(*args, **kwargs), False
            cond_fn(limit, **cond_kwargs)
        except:
            result, exception = (_format_tb(*sys.exc_info(), in_main=True),), True
        
        if not pre_terminate.is_set():
            pre_terminate.set()
            pre_conn.put((result, exception))
        
        monitor_thread.join()
        termination_thread.join()
    
    def wrapper(func):
        @wraps(func)
        def call(*args, **kwargs):
            terminate = Event()
            queue = SimpleQueue()
            
            process = IProcess(target=Main,
                            args=(terminate, queue, func, args, kwargs),
                            daemon=daemon)
            process.start()
            
            #Get results/errors
            result, exception = queue.get()
            
            process.join(timeout=terminate)
            while process.is_alive():
                process.terminate()
            
            #catch errors raised by the callback
            try:
                if callback is not None:
                    callback(*cb_args, **cb_kwargs)
            except:
                if exception:
                    result += (_format_tb(*sys.exc_info()),)
                else:
                    result, exception = (_format_tb(*sys.exc_info()),), True
            
            if exception:
                _raise_tb_stack(result)
            else:
                return result
        
        return call
    return wrapper

def mem_usage(): #in KB
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

def memory(limit, operator=0):
    '''
        This function measures the change in memory usage
        relative to the initial amount of memory defined
        by the 'operator', in order to raise an exception
        passing the 'limit'.
        
        Note: Keep in mind of background processes/threads
        that may skew memory usage.
        
        Arguments:
            *limit          : Is the max amount of memory, in
                            KB, the current process relative to
                            the operator can continue before a
                            MemoryError.
                            
            *operator       : Is the initial memory usage of the
                            current process (default to 0).
    '''
    assert isinstance(limit, (int, float)) and isinstance(operator, (int, float))
    
    delta = mem_usage()-operator
    if delta > limit:
        raise MemoryError("Exceeded local memory limit of '{}' KB. ".format(limit)+
                            "Used '{}' KB.".format(delta))

def timer(limit, operator=None):
    '''
        This function measures the change of time relative
        to the initial point of time defined by the 'operator'
        in order to raise an exception passing the 'limit'.
        
        Note: Keep in mind of background processes/threads
        that may skew the timers accuracy.
        
        Arguments:
            *limit          : Is the max amount of time in
                            seconds the current process
                            relative to the operator can
                            continue before a RuntimeError.
                            
            *operator       : Is the initial point in time of
                            the current process (default to None).
    '''
    assert isinstance(limit, (int, float)) and isinstance(operator, (int, float))
    
    initial_time = operator
    if time.time()-initial_time > limit:
        raise RuntimeError("Exceeded time limit of '{}' second(s).".format(limit))

def thread_children(limit, operator=0):
    '''
        This function measures the number of active threads,
        excluding the main Thread, relative to the initial
        amount defined by the 'operator' in order to raise
        an exception passing the 'limit'.
        
        Arguments:
            *limit          : Is the max amount of active
                            threads the current process
                            relative to the operator can
                            continue before an OverflowError.
                            
            *operator       : Is the initial number of active threads
                            in the current process (default to 0).
    '''
    assert isinstance(limit, int) and isinstance(operator, int)
    
    initial_count = operator
    count = active_count()-2 #exclude local Main and Termination Thread in parent process
    if count-initial_count > limit:
        raise OverflowError("Exceeded the active thread limit of '{}'".format(limit) +
                            " with '{}' thread(s).".format(count-initial_count))

def process_active_count():
    return len(active_children())

def process_children(limit, operator=0):
    '''
        This function measures the number of active processes
        relative to the initial amount defined by the 'operator'
        in order to raise an exception passing the 'limit'.
        
        Arguments:
            *limit          : Is the max amount of active
                            processes the current process
                            relative to the operator can
                            continue before an OverflowError.
                            
            *operator       : Is the initial number of active processes
                            in the current process (default to 0).
    '''
    assert isinstance(limit, int) and isinstance(operator, int)
    
    initial_count = operator
    count = process_active_count()
    if count-initial_count > limit:
        raise OverflowError("Exceeded the active process limit of '{}'".format(limit)+
                            " with '{}' process(es).".format(count-initial_count))

########User Friendly Wrappers########

def RAM_limit(limit, **kwargs): #limit in KB
    '''
        Limits the amount of RAM memory the decorated
        function can use.
        
        Arguments:
            *limit          : Is the max amount of memory, in
                            KB, the current process relative to
                            the operator can continue before a
                            MemoryError.
                            
            **kwargs : See interrupt.
    '''
    return interrupter(memory, limit,
            operator=mem_usage, **kwargs)

def time_limit(limit, **kwargs):
    '''
        Limits the amount of time the decorated
        function can continue to run.
        
        Arguments:
            *limit          : Is the max amount of time in
                            seconds the current process
                            relative to the operator can
                            continue before a RuntimeError.
                            
            **kwargs : See interrupt.
    '''
    return interrupter(timer, limit,
            operator=time.time, **kwargs)

def thread_limit(limit, **kwargs):
    '''
        Limits the number of threads the decorated
        function can create.
        
        Arguments:
            *limit          : Is the max amount of active
                            threads the current process
                            relative to the operator can
                            continue before an OverflowError.
                            
            **kwargs : See interrupt.
    '''
    return interrupter(thread_children, limit,
            operator=active_count, **kwargs)

def process_limit(limit, **kwargs):
    '''
        Limits the number of processes the decorated
        function can create.
        
        Arguments:
            *limit          : Is the max amount of active
                            processes the current process
                            relative to the operator can
                            continue before an OverflowError.
                            
            **kwargs : See interrupt.
    '''
    return interrupter(process_children, limit,
            operator=process_active_count, **kwargs)







