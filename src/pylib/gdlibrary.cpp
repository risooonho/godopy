/* Default generic gdnlib, may be replaced by custom builds */

#include <PyGodot.hpp>

#include "godot/nativescript.h"
#include "godot/gdnative.h"

PyMODINIT_FUNC PyInit_core_types();
PyMODINIT_FUNC PyInit__cython_bindings();
PyMODINIT_FUNC PyInit__python_bindings();
PyMODINIT_FUNC PyInit_utils();

static bool _pygodot_is_initialized = false;

// The name should be the same as the binary's name as it makes this GDNative library also importable by Python
static PyModuleDef _pygodotmodule = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_pygodot",
    .m_doc = "PyGodot Generic GDNative extension",
    .m_size = -1,
};

PyMODINIT_FUNC PyInit__pygodot(void) {
  PyObject *m = PyModule_Create(&_pygodotmodule);

  if (m == NULL) return NULL;

  // TODO: A good place for an easter egg!
  return m;
}

#ifndef PYGODOT_EXPORT
#include <array>
const std::string shelloutput(const char* cmd) {
  std::array<char, 1024> buffer;
  std::string result;
  std::unique_ptr<FILE, decltype(&pclose)> pipe(popen(cmd, "r"), pclose);
  if (!pipe) {
    throw std::runtime_error("popen() failed!");
  }
  while (fgets(buffer.data(), buffer.size(), pipe.get()) != nullptr) {
    result += buffer.data();
  }

  result.erase(std::find_if(result.rbegin(), result.rend(), [](int ch) {
    return !std::isspace(ch);
  }).base(), result.end());

  return result;
}
#endif


static void _ensure_pygodot_is_initialized() {
  if (_pygodot_is_initialized) return;

#ifndef PYGODOT_EXPORT
  static bool use_pipenv = (system("python -c 'import pygodot;_=print' &> /dev/null") != 0);

  if (system(use_pipenv ? "pipenv run python -c 'import pygodot;_=print' &> /dev/null" :
                                     "python -c 'import pygodot;_=print' &> /dev/null") != 0) {
    throw std::runtime_error("unusable Python environment");
  }

  // Copy the correct Python paths for development
  const std::string dev_python_path = use_pipenv ?
    shelloutput("pipenv run python -c \"print(':'.join(__import__('sys').path))\"") :
    shelloutput("python -c \"print(':'.join(__import__('sys').path))\"") ;
  const wchar_t *w_dev_python_path = Py_DecodeLocale(dev_python_path.c_str(), NULL);
  Py_SetPath(w_dev_python_path);
  PyMem_RawFree((void *)w_dev_python_path);
#endif

  PyImport_AppendInittab("_pygodot", PyInit__pygodot);
  PyImport_AppendInittab("core_types", PyInit_core_types);
  // XXX: Cython bindings are not needed in a generic lib
  PyImport_AppendInittab("_cython_bindings", PyInit__cython_bindings);
  PyImport_AppendInittab("_python_bindings", PyInit__python_bindings);
  PyImport_AppendInittab("utils", PyInit_utils);
  PyImport_AppendInittab("nativescript", PyInit_nativescript);
  PyImport_AppendInittab("gdnative", PyInit_gdnative);

  pygodot::PyGodot::python_init();

  // Importing of Cython modules is required to correctly initialize them
  PyObject *mod = NULL;
  // TODO: add Godot error handling
  mod = PyImport_ImportModule("core_types"); if (mod == NULL) return PyErr_Print(); Py_DECREF(mod);
  // XXX: Cython bindings are not needed in a generic lib
  mod = PyImport_ImportModule("_cython_bindings"); if (mod == NULL) return PyErr_Print(); Py_DECREF(mod);
  mod = PyImport_ImportModule("_python_bindings"); if (mod == NULL) return PyErr_Print(); Py_DECREF(mod);
  mod = PyImport_ImportModule("utils"); if (mod == NULL) return PyErr_Print(); Py_DECREF(mod);
  mod = PyImport_ImportModule("nativescript"); if (mod == NULL) return PyErr_Print(); Py_DECREF(mod);
  mod = PyImport_ImportModule("gdnative"); if (mod == NULL) return PyErr_Print(); Py_DECREF(mod);

  _pygodot_is_initialized = true;
}

extern "C" void GDN_EXPORT pygodot_gdnative_init(godot_gdnative_init_options *o) {
    godot::Godot::gdnative_init(o);
    pygodot::PyGodot::set_pythonpath(o);
}

extern "C" void GDN_EXPORT pygodot_gdnative_terminate(godot_gdnative_terminate_options *o) {
  godot::Godot::gdnative_terminate(o);
  pygodot::PyGodot::python_terminate();
}

extern "C" void GDN_EXPORT pygodot_nativescript_init(void *handle) {
  _ensure_pygodot_is_initialized();
  pygodot::PyGodot::nativescript_init(handle);

  if (generic_nativescript_init() == NULL) PyErr_Print(); // TODO: add Godot error handling
}

extern "C" void GDN_EXPORT pygodot_gdnative_singleton() {
  _ensure_pygodot_is_initialized();
  if (generic_gdnative_singleton() == NULL) PyErr_Print(); // TODO: add Godot error handling
}

extern "C" void GDN_EXPORT pygodot_nativescript_terminate(void *handle) {
  pygodot::PyGodot::nativescript_terminate(handle);
}