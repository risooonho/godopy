import os
import re
import sys
import enum
import hashlib

from setuptools import Extension
from setuptools.command.build_ext import build_ext

from mako.template import Template

from ..version import get_version


class ExtType(enum.Enum):
    PROJECT = enum.auto()
    GENERIC_LIBRARY = enum.auto()
    LIBRARY = enum.auto()
    NATIVESCRIPT = enum.auto()


root_dir = os.getcwd()  # XXX
tools_root = os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))
templates_dir = os.path.join(tools_root, 'setup', 'templates')


class GenericGDNativeLibrary(Extension):
    def __init__(self, name):
        self._gdnative_type = ExtType.GENERIC_LIBRARY
        super().__init__(name, sources=[])


class GDNativeLibrary(Extension):
    def __init__(self, name, source, extra_sources=None):
        self._gdnative_type = ExtType.LIBRARY

        sources = [source]

        if extra_sources is not None:
            for src in extra_sources:
                sources.append(src)

        super().__init__(name, sources=sources)


class NativeScript(Extension):
    def __init__(self, name, *, sources=None, class_name=None):
        self._gdnative_type = ExtType.NATIVESCRIPT
        self._nativescript_classname = class_name
        super().__init__(name, sources=(sources or []))


# TODO: Check reserved names (_pygodot, pygodot, cnodes, nodes, utils, gdnative, pyscript + python builtins)!
class gdnative_build_ext(build_ext):
    godot_project = None
    gdnative_library_path = None
    generic_setup = False

    build_context = {
        '__version__': get_version(),
        'godot_headers_path': os.path.join(tools_root, '..', 'godot_headers'),
        'pygodot_bindings_path': os.path.dirname(tools_root),
        'singleton': False,
        'pyx_sources': [],
        'cpp_sources': []
    }

    godot_resources = {}

    def run(self):
        if 'VIRTUAL_ENV' not in os.environ:
            sys.stderr.write("Please run this command inside the virtual environment.\n")
            sys.exit(1)

        for ext in self.extensions:
            print('setting up',
                  ('GDNative %s' if self.godot_project else 'Godot %s') % ext._gdnative_type.name.lower(),
                  ('"res://%s"' if self.godot_project else '"%s"') % ext.name)
            getattr(self, 'collect_godot_%s_data' % ext._gdnative_type.name.lower())(ext)

        if self.generic_setup:
            self.run_generic()
        else:
            self.run_cpp_build()

        for res_path, content in self.godot_resources.items():
            self.write_target_file(os.path.join(self.godot_project.name, res_path), content,
                                   pretty_path='res://%s' % res_path, is_editable_resource=True)

    def run_generic(self):
        source = os.path.join(self.build_context['pygodot_bindings_path'], self.build_context['pygodot_library_name'])
        target = self.build_context['target']

        print(source)
        assert os.path.exists(source)
        print(target, os.path.exists(target), os.path.islink(target))

        if os.path.islink(target) and os.readlink(target) == source and not self.force:
            print('skip linking "%s"' % make_relative_path(target))
            return

        # Remove if the target is not a correct symlink
        if (os.path.exists(target) or os.path.islink(target)) and not self.dry_run:
            os.unlink(target)

        target_dir = os.path.dirname(target)
        if not os.path.exists(target_dir) and not self.dry_run:
            os.makedirs(target_dir)

        print('linking "%s"' % make_relative_path(target))
        if not self.dry_run:
            os.symlink(source, target)

    def run_cpp_build(self):
        cpp_lib_template = Template(filename=os.path.join(templates_dir, 'gdlibrary.cpp.mako'))
        cpp_lib_path = self.build_context['cpp_library_path']
        self.write_target_file(cpp_lib_path, cpp_lib_template.render(**self.build_context))

        self.build_context['cpp_sources'].append(make_relative_path(self.build_context['cpp_library_path']))

        scons_template = Template(filename=os.path.join(templates_dir, 'SConstruct.mako'))
        self.write_target_file('SConstruct', scons_template.render(**self.build_context))

        scons = os.path.join(sys.prefix, 'Scripts', 'scons') if sys.platform == 'win32' else 'scons'

        if not self.dry_run:
            self.spawn([scons])

    def write_target_file(self, path, content, pretty_path=None, is_editable_resource=False):
        if pretty_path is None:
            pretty_path = path

        if os.path.exists(path) and not self.force:
            # Check if there are any changes
            new_hash = hashlib.sha1(content.encode('utf-8'))
            with open(path, encoding='utf-8') as fp:
                old_hash = hashlib.sha1(fp.read().encode('utf-8'))
            if old_hash.digest() == new_hash.digest():
                print('skip writing "%s"' % pretty_path)
                return
            elif is_editable_resource and not self.force:
                # Do not overwrite user resources without --force flag
                print('WARNING! modified resource already exists: "%s"' % pretty_path)
                return

        print('writing "%s"' % pretty_path, path)
        if not self.dry_run:
            dirname, basename = os.path.split(path)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)

            with open(path, 'w', encoding='utf-8') as fp:
                fp.write(content)

    def collect_godot_project_data(self, ext):
        self.godot_project = ext

    def collect_godot_generic_library_data(self, ext):
        if self.godot_project is None:
            sys.stderr.write("Can't build a GDNative library without a Godot project.\n\n")
            sys.exit(1)

        if self.gdnative_library_path is not None:
            sys.stderr.write("Can't build multiple GDNative libraries.\n")
            sys.exit(1)

        if sys.platform == 'darwin':
            platform = 'OSX.64'
        elif sys.platform.startswith('linux'):
            platform = 'X11.64'
        elif sys.platform == 'win32':
            platform = 'Windows.64'
        else:
            sys.stderr.write("Can't build for '%s' platform yet.\n" % sys.platform)
            sys.exit(1)

        if sys.maxsize <= 2**32:
            sys.stderr.write("32-bit platforms are not supported.\n")
            sys.exit(1)

        ext_name = self.godot_project.get_setuptools_name(ext.name, validate='.gdnlib')
        ext_path = self.get_ext_fullpath(ext_name)
        godot_root = ensure_godot_project_path(ext_path)

        dst_dir, dst_fullname = os.path.split(ext_path)
        dst_name_parts = dst_fullname.split('.')
        src_name = '.'.join(['_pygodot', *dst_name_parts[1:]])  # differs from non-generic name, has extension

        binext_path = os.path.join(godot_root, self.godot_project.binary_path, dst_fullname)

        self.build_context['pygodot_library_name'] = src_name
        self.build_context['target'] = binext_path
        self.build_context['library_name'] = '_pygodot'

        dst_name = dst_name_parts[0]
        gdnlib_respath = make_resource_path(godot_root, os.path.join(dst_dir, dst_name + '.gdnlib'))
        self.gdnative_library_path = gdnlib_respath
        self.generic_setup = True

        context = dict(
            singleton=False,
            load_once=True,
            symbol_prefix='pygodot_',
            reloadable=False,
            libraries={platform: make_resource_path(godot_root, binext_path)},
            dependencies={platform: ''}
        )

        self.make_godot_resource('gdnlib.mako', gdnlib_respath, context)

    def collect_godot_library_data(self, ext):
        if self.godot_project is None:
            sys.stderr.write("Can't build a GDNative library without a Godot project.\n\n")
            sys.exit(1)

        if self.gdnative_library_path is not None:
            sys.stderr.write("Can't build multiple GDNative libraries.\n")
            sys.exit(1)

        if sys.platform == 'darwin':
            platform = 'OSX.64'
        elif sys.platform.startswith('linux'):
            platform = 'X11.64'
        elif sys.platform == 'win32':
            platform = 'Windows.64'
        else:
            sys.stderr.write("Can't build for '%s' platform yet.\n" % sys.platform)
            sys.exit(1)

        if sys.maxsize <= 2**32:
            sys.stderr.write("32-bit platforms are not supported.\n")
            sys.exit(1)

        ext_name = self.godot_project.get_setuptools_name(ext.name, validate='.gdnlib')
        ext_path = self.get_ext_fullpath(ext_name)
        godot_root = ensure_godot_project_path(ext_path)

        dst_dir, dst_fullname = os.path.split(ext_path)
        dst_name_parts = dst_fullname.split('.')
        dst_name_parts[0] = 'lib' + dst_name_parts[0]
        # if dst_name_parts[0] == 'gdlibrary':
        #    dst_name_parts[0] = '_gdlibrary'
        _ext = dst_name_parts[-1]
        if _ext == 'pyd':
            _ext = 'dll'
        dst_fullname = dst_name_parts[0] + '.' + _ext  # '.'.join(dst_name_parts)
        # staticlib_name = '.'.join(['_pygodot', *dst_name_parts[1:-1]])
        staticlib_name = 'libpygodot.%s.debug.64' % platform.lower().split('.')[0]

        binext_path = os.path.join(godot_root, self.godot_project.binary_path, dst_fullname)

        cpp_library_base_path = re.sub(r'\.pyx?$', '.cpp', ext.sources[0])
        cpp_library_dir, cpp_library_unprefixed = os.path.split(cpp_library_base_path)
        self.build_context['cpp_library_path'] = \
            os.path.join(self.godot_project.shadow_name, cpp_library_dir, '_' + cpp_library_unprefixed)

        self.build_context['pygodot_library_name'] = staticlib_name
        self.build_context['target'] = make_relative_path(binext_path)

        dst_name = dst_name_parts[0]
        self.build_context['library_name'] = dst_name
        gdnlib_respath = make_resource_path(godot_root, os.path.join(dst_dir, dst_name[3:] + '.gdnlib'))
        self.gdnative_library_path = gdnlib_respath
        self.generic_setup = False

        context = dict(
            singleton=False,
            load_once=True,
            symbol_prefix='pygodot_',
            reloadable=False,
            libraries={platform: make_resource_path(godot_root, binext_path)},
            dependencies={platform: ''}
        )

        self.make_godot_resource('gdnlib.mako', gdnlib_respath, context)
        self.collect_sources(ext.sources)

    def collect_godot_nativescript_data(self, ext):
        if not self.gdnative_library_path:
            sys.stderr.write("Can't build a NativeScript extension without a GDNative library.\n")
            sys.exit(1)

        ext_name = self.godot_project.get_setuptools_name(ext.name, validate='.gdns')
        ext_path = self.get_ext_fullpath(ext_name)
        godot_root = ensure_godot_project_path(ext_path)

        dst_dir, dst_fullname = os.path.split(ext_path)
        dst_name_parts = dst_fullname.split('.')
        dst_name = dst_name_parts[0]
        gdns_path = os.path.join(dst_dir, dst_name + '.gdns')

        if dst_name == self.build_context['library_name']:
            raise NameError("'%s' name is already used. Please select a different name\n" % dst_name)

        classname = ext._nativescript_classname or dst_name
        context = dict(gdnlib_resource=self.gdnative_library_path, classname=classname)

        self.make_godot_resource('gdns.mako', make_resource_path(godot_root, gdns_path), context)
        self.collect_sources(ext.sources)

    def make_godot_resource(self, template_filename, path, context):
        template = Template(filename=os.path.join(templates_dir, template_filename))
        self.godot_resources[path] = template.render(**context)

    def collect_sources(self, sources):
        cpp_sources = []

        for pyx_source in sources:
            if pyx_source.endswith('.cpp'):
                cpp_sources.append(pyx_source)
                continue

            source = os.path.join(self.godot_project.shadow_name, pyx_source)
            target = source.replace('.pyx', '.cpp')
            target_dir, target_name = os.path.split(target)

            # varnames should be unique due to the way Python modules are initialized
            varname, _ = os.path.splitext(target_name)

            self.build_context['pyx_sources'].append((varname, target, source))

        for cpp_source in cpp_sources:
            source = os.path.join(self.godot_project.shadow_name, cpp_source)
            self.build_context['cpp_sources'].append(make_relative_path(source))


def ensure_godot_project_path(path):
    godot_root = detect_godot_project(path)

    if not godot_root:
        sys.stderr.write("No Godot project detected.\n")
        sys.exit(1)

    return os.path.realpath(godot_root)


def detect_godot_project(dir, fn='project.godot'):
    if not dir or not fn:
        return

    if os.path.isdir(dir) and 'project.godot' in os.listdir(dir):
        return dir

    return detect_godot_project(*os.path.split(dir))


def make_resource_path(godot_root, path):
    return path.replace(godot_root, '').lstrip(os.sep).replace(os.sep, '/')


def make_relative_path(path):
    return os.path.realpath(path).replace(root_dir, '').lstrip(os.sep).replace(os.sep, '/')