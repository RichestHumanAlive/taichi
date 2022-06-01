import copy
import functools
import itertools
import os
from errno import EEXIST
from tempfile import mkstemp

import pytest
from taichi._lib import core as _ti_core
from taichi.lang import cc, cpu, cuda, dx11, gpu, metal, opengl, vulkan
from taichi.lang.misc import is_arch_supported

import taichi as ti


# Helper functions
def get_rel_eps():
    arch = ti.lang.impl.current_cfg().arch
    if arch == ti.opengl:
        return 1e-3
    if arch == ti.metal:
        # Debatable, different hardware could yield different precisions
        # On AMD Radeon Pro 5500M, 1e-6 works fine...
        # https://github.com/taichi-dev/taichi/pull/1779
        return 1e-4
    return 1e-6


def mkdir_p(dir_path):
    '''Creates a directory. equivalent to using mkdir -p on the command line'''

    try:
        os.makedirs(dir_path)
    except OSError as exc:  # Python > 2.5
        if exc.errno == EEXIST and os.path.isdir(dir_path):
            pass
        else:
            raise


def approx(expected, **kwargs):
    '''Tweaked pytest.approx for OpenGL low precisions'''
    class boolean_integer:
        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            return bool(self.value) == bool(other)

        def __ne__(self, other):
            return bool(self.value) != bool(other)

    if isinstance(expected, bool):
        return boolean_integer(expected)

    kwargs['rel'] = max(kwargs.get('rel', 1e-6), get_rel_eps())

    import pytest  # pylint: disable=C0415
    return pytest.approx(expected, **kwargs)


def allclose(x, y, **kwargs):
    '''Same as: x == approx(y, **kwargs)'''
    return x == approx(y, **kwargs)


def make_temp_file(*args, **kwargs):
    '''Create a temporary file'''

    fd, name = mkstemp(*args, **kwargs)
    os.close(fd)
    return name


class TestParam:
    def __init__(self, value, required_extensions):
        self._value = value
        self._required_extensions = required_extensions

    @property
    def value(self):
        return self._value

    @property
    def required_extensions(self):
        return self._required_extensions


_test_features = {
    #"packed":
    # [TestValue(True, []),
    #  TestValue(False, [])],
    "dynamic_index":
    [TestParam(True, [ti.extension.dynamic_index]),
     TestParam(False, [])]
}


def expected_archs():
    """
    Reads the environment variable `TI_WANTED_ARCHS` (usually set by option `-a` in `python tests/run_tests.py`)
    and gets all expected archs on the machine.
    If `TI_WANTED_ARCHS` is set and does not start with `^`, archs specified in it will be returned.
    If `TI_WANTED_ARCHS` starts with `^` (usually when option `-n` is specified in `python tests/run_tests.py`),
    all supported archs except archs specified in it will be returned.
    If `TI_WANTED_ARCHS` is not set, all supported archs will be returned.
    Returns:
        List[taichi_core.Arch]: All expected archs on the machine.
    """
    archs = set([cpu, cuda, metal, vulkan, opengl, cc])
    # TODO: now expected_archs is not called per test so we cannot test it
    archs = set(
        filter(functools.partial(is_arch_supported, use_gles=False), archs))

    wanted_archs = os.environ.get('TI_WANTED_ARCHS', '')
    want_exclude = wanted_archs.startswith('^')
    if want_exclude:
        wanted_archs = wanted_archs[1:]
    wanted_archs = wanted_archs.split(',')
    # Note, ''.split(',') gives you [''], which is not an empty array.
    expanded_wanted_archs = set([])
    for arch in wanted_archs:
        if arch == '':
            continue
        if arch == 'cpu':
            expanded_wanted_archs.add(cpu)
        elif arch == 'gpu':
            expanded_wanted_archs.update(gpu)
        else:
            expanded_wanted_archs.add(_ti_core.arch_from_name(arch))
    if len(expanded_wanted_archs) == 0:
        return list(archs)
    if want_exclude:
        expected = archs - expanded_wanted_archs
    else:
        expected = expanded_wanted_archs
    return list(expected)


def test(arch=None, exclude=None, require=None, **options):
    """
    Performs tests on archs in `expected_archs()` which are in `arch` and not in `exclude` and satisfy `require`
.. function:: ti.test(arch=[], exclude=[], require=[], **options)

    :parameter arch: backends to include
    :parameter exclude: backends to exclude
    :parameter require: extensions required
    :parameter options: other options to be passed into ``ti.init``

    """

    if arch is None:
        arch = []
    if exclude is None:
        exclude = []
    if require is None:
        require = []
    if not isinstance(arch, (list, tuple)):
        arch = [arch]
    if not isinstance(exclude, (list, tuple)):
        exclude = [exclude]
    if not isinstance(require, (list, tuple)):
        require = [require]
    archs_expected = expected_archs()
    if len(arch) == 0:
        arch = archs_expected
    else:
        arch = [v for v in arch if v in archs_expected]

    marks = []  # A list of pytest.marks to apply on the test function
    if len(arch) == 0:
        marks.append(pytest.mark.skip(reason='No supported archs'))
    else:
        arch_params_sets = [arch, *_test_features.values()]
        # List of (arch, options) to parametrize the test function
        parameters = []
        for req_arch, *req_params in itertools.product(*arch_params_sets):
            if (req_arch not in arch) or (req_arch in exclude):
                continue

            if not all(
                    _ti_core.is_extension_supported(req_arch, e)
                    for e in require):
                continue

            current_options = copy.deepcopy(options)
            for feature, param in zip(_test_features, req_params):
                value = param.value
                required_extensions = param.required_extensions
                if current_options.setdefault(feature, value) != value or any(
                        not _ti_core.is_extension_supported(req_arch, e)
                        for e in required_extensions):
                    break
            else:  # no break occurs, required extensions are supported
                parameters.append((req_arch, current_options))

        if not parameters:
            marks.append(
                pytest.mark.skip(
                    reason='No all required extensions are supported'))
        else:
            marks.append(
                pytest.mark.parametrize(
                    "req_arch,req_options",
                    parameters,
                    ids=[
                        f"arch={arch.name}-{i}"
                        if len(parameters) > 1 else f"arch={arch.name}"
                        for i, (arch, _) in enumerate(parameters)
                    ]))

    def decorator(func):
        func.__ti_test__ = True  # Mark the function as a taichi test
        for mark in reversed(marks):  # Apply the marks in reverse order
            func = mark(func)
        return func

    return decorator


__all__ = [
    'test',
]
