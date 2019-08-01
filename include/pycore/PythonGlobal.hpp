#ifndef PYTHON_GLOBAL_HPP
#define PYTHON_GLOBAL_HPP

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <gdnative_api_struct.gen.h>

namespace pygodot {

class PyGodot {

public:
	static void set_pythonpath(godot_gdnative_init_options *o);
	static void python_init();
	static void python_terminate();

  static void nativescript_init(void *handle, bool init_cython=true, bool init_python=true);
  static void nativescript_terminate(void *handle);

  static void set_cython_language_index(int language_index);
  static void set_python_language_index(int language_index);
};

} // namespace pygodot

#endif