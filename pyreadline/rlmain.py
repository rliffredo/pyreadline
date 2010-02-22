# -*- coding: utf-8 -*-
#*****************************************************************************
#       Copyright (C) 2003-2006 Gary Bishop.
#       Copyright (C) 2006  Jorgen Stenarson. <jorgen.stenarson@bostream.nu>
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#*****************************************************************************
u''' an attempt to implement readline for Python in Python using ctypes'''
import sys,os,re,time
from glob import glob

import release

import pyreadline.lineeditor.lineobj as lineobj
import pyreadline.lineeditor.history as history
import pyreadline.clipboard as clipboard
import pyreadline.console as console
import pyreadline.logger as logger 

from pyreadline.keysyms.common import make_KeyPress_from_keydescr
from pyreadline.unicode_helper import ensure_unicode
from logger import log
from modes import editingmodes
from error import ReadlineError, GetSetError

in_ironpython = u"IronPython" in sys.version
if in_ironpython:#ironpython does not provide a prompt string to readline
    import System    
    default_prompt = u">>> "
else:
    default_prompt = u""
    import pdb


class MockConsoleError(Exception):
    pass

class MockConsole(object):
    u"""object used during refactoring. Should raise errors when someone tries to use it.
    """
    def __setattr__(self, x):
        raise MockConsoleError(u"Should not try to get attributes from MockConsole")

    def cursor(self, size=50):
        pass

class BaseReadline(object):
    def __init__(self):
        self.allow_ctrl_c = False
        self.ctrl_c_tap_time_interval = 0.3

        self.debug = False
        self.bell_style = u'none'
        self.mark = -1
        self.console=MockConsole()
        self.disable_readline = False
        # this code needs to follow l_buffer and history creation
        self.editingmodes = [mode(self) for mode in editingmodes]
        for mode in self.editingmodes:
            mode.init_editing_mode(None)
        self.mode = self.editingmodes[0]

        self.read_inputrc()
        log(u"\n".join(self.mode.rl_settings_to_string()))

        self.callback = None

    def parse_and_bind(self, string):
        u'''Parse and execute single line of a readline init file.'''
        try:
            log(u'parse_and_bind("%s")' % string)
            if string.startswith(u'#'):
                return
            if string.startswith(u'set'):
                m = re.compile(ur'set\s+([-a-zA-Z0-9]+)\s+(.+)\s*$').match(string)
                if m:
                    var_name = m.group(1)
                    val = m.group(2)
                    try:
                        setattr(self, var_name.replace(u'-',u'_'), val)
                    except AttributeError:
                        log(u'unknown var="%s" val="%s"' % (var_name, val))
                else:
                    log(u'bad set "%s"' % string)
                return
            m = re.compile(ur'\s*(.+)\s*:\s*([-a-zA-Z]+)\s*$').match(string)
            if m:
                key = m.group(1)
                func_name = m.group(2)
                py_name = func_name.replace(u'-', u'_')
                try:
                    func = getattr(self.mode, py_name)
                except AttributeError:
                    log(u'unknown func key="%s" func="%s"' % (key, func_name))
                    if self.debug:
                        print u'pyreadline parse_and_bind error, unknown function to bind: "%s"' % func_name
                    return
                self.mode._bind_key(key, func)
        except:
            log(u'error')
            raise

    def _set_prompt(self, prompt):
        self.mode.prompt = prompt
        
    def _get_prompt(self):
        return self.mode.prompt
    
    prompt = property(_get_prompt, _set_prompt)


    def get_line_buffer(self):
        u'''Return the current contents of the line buffer.'''
        return self.mode.l_buffer.get_line_text()

    def insert_text(self, string):
        u'''Insert text into the command line.'''
        self.mode.insert_text(string)
        
    def read_init_file(self, filename=None): 
        u'''Parse a readline initialization file. The default filename is the last filename used.'''
        log(u'read_init_file("%s")' % filename)

    #History file book keeping methods (non-bindable)
    
    def add_history(self, line):
        u'''Append a line to the history buffer, as if it was the last line typed.'''
        self.mode._history.add_history(line)

    def get_history_length(self ):
        u'''Return the desired length of the history file.

        Negative values imply unlimited history file size.'''
        return self.mode._history.get_history_length()

    def set_history_length(self, length): 
        u'''Set the number of lines to save in the history file.

        write_history_file() uses this value to truncate the history file
        when saving. Negative values imply unlimited history file size.
        '''
        self.mode._history.set_history_length(length)

    def clear_history(self):
        u'''Clear readline history'''
        self.mode._history.clear_history()

    def read_history_file(self, filename=None): 
        u'''Load a readline history file. The default filename is ~/.history.'''
        if filename is None:
            filename = self.mode._history.history_filename
        log(u"read_history_file from %s"%ensure_unicode(filename))
        self.mode._history.read_history_file(filename)

    def write_history_file(self, filename=None): 
        u'''Save a readline history file. The default filename is ~/.history.'''
        self.mode._history.write_history_file(filename)

    #Completer functions

    def set_completer(self, function=None): 
        u'''Set or remove the completer function.

        If function is specified, it will be used as the new completer
        function; if omitted or None, any completer function already
        installed is removed. The completer function is called as
        function(text, state), for state in 0, 1, 2, ..., until it returns a
        non-string value. It should return the next possible completion
        starting with text.
        '''
        log(u'set_completer')
        self.mode.completer = function

    def get_completer(self): 
        u'''Get the completer function. 
        '''
        log(u'get_completer')
        return self.mode.completer

    def get_begidx(self):
        u'''Get the beginning index of the readline tab-completion scope.'''
        return self.mode.begidx

    def get_endidx(self):
        u'''Get the ending index of the readline tab-completion scope.'''
        return self.mode.endidx

    def set_completer_delims(self, string):
        u'''Set the readline word delimiters for tab-completion.'''
        self.mode.completer_delims = string

    def get_completer_delims(self):
        u'''Get the readline word delimiters for tab-completion.'''
        return self.mode.completer_delims.encode("ascii") 

    def set_startup_hook(self, function=None): 
        u'''Set or remove the startup_hook function.

        If function is specified, it will be used as the new startup_hook
        function; if omitted or None, any hook function already installed is
        removed. The startup_hook function is called with no arguments just
        before readline prints the first prompt.

        '''
        self.mode.startup_hook = function

    def set_pre_input_hook(self, function=None):
        u'''Set or remove the pre_input_hook function.

        If function is specified, it will be used as the new pre_input_hook
        function; if omitted or None, any hook function already installed is
        removed. The pre_input_hook function is called with no arguments
        after the first prompt has been printed and just before readline
        starts reading input characters.

        '''
        self.mode.pre_input_hook = function

#Functions that are not relevant for all Readlines but should at least have a NOP

    def _bell(self):
        pass

#
# Standard call, not available for all implementations
#
    
    def readline(self, prompt=u''):
        raise NotImplementedError

#
# Callback interface
#
    def process_keyevent(self, keyinfo):
        return self.mode.process_keyevent(keyinfo)
        
    def readline_setup(self, prompt=u""):
        return self.mode.readline_setup(prompt)

    def keyboard_poll(self):
        return self.mode._readline_from_keyboard_poll()

    def callback_handler_install(self, prompt, callback):
        u'''bool readline_callback_handler_install ( string prompt, callback callback)
        Initializes the readline callback interface and terminal, prints the prompt and returns immediately
        '''
        self.callback = callback
        self.readline_setup(prompt)

    def callback_handler_remove(self):
        u'''Removes a previously installed callback handler and restores terminal settings'''
        self.callback = None

    def callback_read_char(self):
        u'''Reads a character and informs the readline callback interface when a line is received'''
        if self.keyboard_poll():
            line = self.get_line_buffer() + u'\n'
            # however there is another newline added by
            # self.mode.readline_setup(prompt) which is called by callback_handler_install
            # this differs from GNU readline
            self.add_history(self.mode.l_buffer)
            # TADA:
            self.callback(line)

    def read_inputrc(self, #in 2.4 we cannot call expanduser with unicode string
                     inputrcpath=os.path.expanduser("~/pyreadlineconfig.ini")):
        modes = dict([(x.mode,x) for x in self.editingmodes])
        mode = self.editingmodes[0].mode

        def setmode(name):
            self.mode = modes[name]

        def bind_key(key, name):
            import new
            if callable(name):
                modes[mode]._bind_key(key, new.instancemethod(name, modes[mode], modes[mode].__class__))
            elif hasattr(modes[mode], name):
                modes[mode]._bind_key(key, getattr(modes[mode], name))
            else:
                print u"Trying to bind unknown command '%s' to key '%s'"%(name, key)

        def un_bind_key(key):
            keyinfo = make_KeyPress_from_keydescr(key).tuple()
            if keyinfo in modes[mode].key_dispatch:
                del modes[mode].key_dispatch[keyinfo]

        def bind_exit_key(key):
            modes[mode]._bind_exit_key(key)
            
        def un_bind_exit_key(key):
            keyinfo = make_KeyPress_from_keydescr(key).tuple()
            if keyinfo in modes[mode].exit_dispatch:
                del modes[mode].exit_dispatch[keyinfo]

        def setkill_ring_to_clipboard(killring):
            import pyreadline.lineeditor.lineobj 
            pyreadline.lineeditor.lineobj.kill_ring_to_clipboard = killring

        def sethistoryfilename(filename):
            self.mode._history.history_filename=os.path.expanduser(filename)

        def setbellstyle(mode):
            self.bell_style = mode

        def disable_readline(mode):
            self.disable_readline = mode

        def sethistorylength(length):
            self.mode._history.history_length = int(length)

        def allow_ctrl_c(mode):
            log(u"allow_ctrl_c:%s:%s"%(self.allow_ctrl_c, mode))
            self.allow_ctrl_c = mode
 
        def setbellstyle(mode):
            self.bell_style = mode
 
        def show_all_if_ambiguous(mode):
            self.mode.show_all_if_ambiguous = mode
        
        def ctrl_c_tap_time_interval(mode):
            self.ctrl_c_tap_time_interval = mode
        
        def mark_directories(mode):
            self.mode.mark_directories = mode
        
        def completer_delims(delims):
            self.mode.completer_delims = delims
        
        def complete_filesystem(delims):
            self.mode.complete_filesystem = delims.lower()
        
        def debug_output(on, filename=u"pyreadline_debug_log.txt"): #Not implemented yet
            if on in [u"on", u"on_nologfile"]:
                self.debug=True

            if on == "on":
                logger.start_file_log(filename)
                logger.start_socket_log()
                logger.log(u"STARTING LOG")
            elif on == u"on_nologfile":
                logger.start_socket_log()
                logger.log(u"STARTING LOG")
            else:
                logger.log(u"STOPING LOG")
                logger.stop_file_log()
                logger.stop_socket_log()
        
        _color_trtable={u"black":0,      u"darkred":4,  u"darkgreen":2, 
                        u"darkyellow":6, u"darkblue":1, u"darkmagenta":5,
                        u"darkcyan":3,   u"gray":7,     u"red":4+8,
                        u"green":2+8,    u"yellow":6+8, u"blue":1+8,
                        u"magenta":5+8,  u"cyan":3+8,   u"white":7+8}
        
        def set_prompt_color(color):
            self.prompt_color = self._color_trtable.get(color.lower(),7)            
            
        def set_input_color(color):
            self.command_color=self._color_trtable.get(color.lower(),7)            

        loc = {u"branch":release.branch,
               u"version":release.version,
               u"mode":mode,
               u"modes":modes,
               u"set_mode":setmode,
               u"bind_key":bind_key,
               u"disable_readline":disable_readline,
               u"bind_exit_key":bind_exit_key,
               u"un_bind_key":un_bind_key,
               u"un_bind_exit_key":un_bind_exit_key,
               u"bell_style":setbellstyle,
               u"mark_directories":mark_directories,
               u"show_all_if_ambiguous":show_all_if_ambiguous,
               u"completer_delims":completer_delims,
               u"complete_filesystem":complete_filesystem,
               u"debug_output":debug_output,
               u"history_filename":sethistoryfilename,
               u"history_length":sethistorylength,
               u"set_prompt_color":set_prompt_color,
               u"set_input_color":set_input_color,
               u"allow_ctrl_c":allow_ctrl_c,
               u"ctrl_c_tap_time_interval":ctrl_c_tap_time_interval,
               u"kill_ring_to_clipboard":setkill_ring_to_clipboard,
              }
        if os.path.isfile(inputrcpath): 
            try:
                execfile(inputrcpath, loc, loc)
            except Exception,x:
                raise
                import traceback
                print >>sys.stderr, u"Error reading .pyinputrc"
                filepath,lineno=traceback.extract_tb(sys.exc_traceback)[1][:2]
                print >>sys.stderr, u"Line: %s in file %s"%(lineno, filepath)
                print >>sys.stderr, x
                raise ReadlineError(u"Error reading .pyinputrc")



class Readline(BaseReadline):
    """Baseclass for readline based on a console
    """
    def __init__(self):
        BaseReadline.__init__(self)
        self.console = console.Console()
        self.selection_color = self.console.saveattr<<4
        self.command_color = None
        self.prompt_color = None
        self.size = self.console.size()

        # variables you can control with parse_and_bind

#  To export as readline interface


##  Internal functions

    def _bell(self):
        u'''ring the bell if requested.'''
        if self.bell_style == u'none':
            pass
        elif self.bell_style == u'visible':
            raise NotImplementedError(u"Bellstyle visible is not implemented yet.")
        elif self.bell_style == u'audible':
            self.console.bell()
        else:
            raise ReadlineError(u"Bellstyle %s unknown."%self.bell_style)

    def _clear_after(self):
        c = self.console
        x, y = c.pos()
        w, h = c.size()
        c.rectangle((x, y, w+1, y+1))
        c.rectangle((0, y+1, w, min(y+3,h)))

    def _set_cursor(self):
        c = self.console
        xc, yc = self.prompt_end_pos
        w, h = c.size()
        xc += self.mode.l_buffer.visible_line_width()
        while(xc >= w):
            xc -= w
            yc += 1
        c.pos(xc, yc)

    def _print_prompt(self):
        c = self.console
        x, y = c.pos()
        
        n = c.write_scrolling(self.prompt, self.prompt_color)
        self.prompt_begin_pos = (x, y - n)
        self.prompt_end_pos = c.pos()
        self.size = c.size()

    def _update_prompt_pos(self, n):
        if n != 0:
            bx, by = self.prompt_begin_pos
            ex, ey = self.prompt_end_pos
            self.prompt_begin_pos = (bx, by - n)
            self.prompt_end_pos = (ex, ey - n)

    def _update_line(self):
        c = self.console
        l_buffer = self.mode.l_buffer
        c.cursor(0)         #Hide cursor avoiding flicking
        c.pos(*self.prompt_begin_pos)
        self._print_prompt()
        ltext = l_buffer.quoted_text()
        if l_buffer.enable_selection and (l_buffer.selection_mark >= 0):
            start = len(l_buffer[:l_buffer.selection_mark].quoted_text())
            stop  = len(l_buffer[:l_buffer.point].quoted_text())
            if start > stop:
                stop,start = start,stop
            n = c.write_scrolling(ltext[:start], self.command_color)
            n = c.write_scrolling(ltext[start:stop], self.selection_color)
            n = c.write_scrolling(ltext[stop:], self.command_color)
        else:
            n = c.write_scrolling(ltext, self.command_color)

        x, y = c.pos()       #Preserve one line for Asian IME(Input Method Editor) statusbar
        w, h = c.size()
        if (y >= h - 1) or (n > 0):
            c.scroll_window(-1)
            c.scroll((0, 0, w, h), 0, -1)
            n += 1

        self._update_prompt_pos(n)
        if hasattr(c, u"clear_to_end_of_window"): #Work around function for ironpython due 
            c.clear_to_end_of_window()          #to System.Console's lack of FillFunction
        else:
            self._clear_after()
        
        #Show cursor, set size vi mode changes size in insert/overwrite mode
        c.cursor(1, size=self.mode.cursor_size)  
        self._set_cursor()


    def callback_read_char(self):
        #Override base to get automatic newline
        u'''Reads a character and informs the readline callback interface when a line is received'''
        if self.keyboard_poll():
            line = self.get_line_buffer() + u'\n'
            self.console.write(u"\r\n")
            # however there is another newline added by
            # self.mode.readline_setup(prompt) which is called by callback_handler_install
            # this differs from GNU readline
            self.add_history(self.mode.l_buffer)
            # TADA:
            self.callback(line)


    def event_available(self):
        return self.console.peek() or (len(self.paste_line_buffer) > 0)

        
    def _readline_from_keyboard(self):
        while 1:
            if self._readline_from_keyboard_poll():
                break

    def _readline_from_keyboard_poll(self):
        pastebuffer = self.mode.paste_line_buffer
        if len(pastebuffer) > 0:
            #paste first line in multiline paste buffer
            self.l_buffer = lineobj.ReadLineTextBuffer(pastebuffer[0])
            self._update_line()
            self.mode.paste_line_buffer = pastebuffer[1:]
            return True

        c = self.console
        def nop(e):
            pass
        try:
            event = c.getkeypress()
        except KeyboardInterrupt:
            event = self.handle_ctrl_c()
        result = self.mode.process_keyevent(event.keyinfo)
        self._update_line()
        return result

    def readline_setup(self, prompt=u''):
        BaseReadline.readline_setup(self, prompt)
        self._print_prompt()
        self._update_line()

    def readline(self, prompt=u''):
        self.readline_setup(prompt)
        self.ctrl_c_timeout = time.time()
        self._readline_from_keyboard()
        self.console.write(u'\r\n')
        log(u'returning(%s)' % self.get_line_buffer())
        return self.get_line_buffer() + u'\n'

    def handle_ctrl_c(self):
        from pyreadline.keysyms.common import KeyPress
        from pyreadline.console.event import Event
        log(u"KBDIRQ")
        event = Event(0,0)
        event.char = u"c"
        event.keyinfo = KeyPress(u"c", shift=False, control=True, 
                                 meta=False, keyname=None)
        if self.allow_ctrl_c:
            now = time.time()
            if (now - self.ctrl_c_timeout) < self.ctrl_c_tap_time_interval:
                log(u"Raise KeyboardInterrupt")
                raise KeyboardInterrupt
            else:
                self.ctrl_c_timeout = now
        else:
            raise KeyboardInterrupt
        return event

