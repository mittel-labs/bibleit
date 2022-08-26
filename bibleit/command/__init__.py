import sys

from bibleit import config
from bibleit.command import core
from importlib import import_module

_prefix = "bibleit.command"
_default_module = "core"

def _list_methods(module):
    return {name for name in dir(module) if not name.startswith("_")}

def eval_module(name):
    target = f"{_prefix}.{name}"
    
    try:
        if target not in sys.modules:
            return import_module(target)
        return sys.modules[target]
    except ModuleNotFoundError as e:
        if config.debug:
            print(e)
        return eval_module(_default_module)


def eval(ctx, *line, module=None):
    """Evaluate a function with arbitrary arguments."""
    if module is None:
        module = _default_module
    try:
        ctx.module = eval_module(module)
        ctx.methods = sorted(_list_methods(ctx.module) - _list_methods(sys.builtin_module_names))

        name, *args = line
        target = f"{'{} '.format(module) if module != _default_module else ''}{name}{' {}'.format(' '.join(args)) if args else ''}"
        if name in ctx.methods:
            fn = getattr(ctx.module, name)
            return fn(ctx, *args)        
    except AssertionError as e:
        print(f"Error: {e}")
    except Exception as e:
        core.help(ctx, name)
    else:
        print(f"Error: command '{target}' not found")