import os
import shutil
import tempfile
import unittest
from unittest import mock

from madgraph import InvalidCmd
import madgraph.core.base_objects as base_objects
import madgraph.core.diagram_generation as diagram_generation

from double_counting import DoubleCountingInterface


class TestDoubleCounting(unittest.TestCase):

    def setUp(self):
        self.cmd = DoubleCountingInterface()

    def do(self, line):
        self.cmd.exec_cmd(line)

    def test_check_double_counting_groups(self):
        """check double_counting compares generated and requested diagram sets"""
        self.do('import model sm')
        self.do('generate e+ e- > e+ e-')

        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > e+ e- }')
        self.assertEqual(len(shared), 4)

        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > e+ e- & e+ e- > mu+ mu- }')
        self.assertEqual(len(shared), 4)

        self.do('check double_counting { e+ e- > e+ e- }')

        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > z > e+ e- }')
        self.assertEqual(len(shared), 1)

        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > mu+ mu- }')
        self.assertEqual(len(shared), 0)

        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > e+ e- } { e+ e- > z > e+ e- }')
        self.assertEqual(len(shared), 1)
        self.assertEqual(list(shared.values())[0], set(['A', 'B']))

        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > z > e+ e- } { e+ e- > e+ e- }')
        self.assertEqual(len(shared), 1)

        self.do('add process e+ e- > z > e+ e-')
        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > z > e+ e- }')
        self.assertEqual(len(shared), 1)
        self.assertEqual(list(shared.values())[0], set(['current', 'argument']))

    def test_check_double_counting_standalone(self):
        """check double_counting can compare two sets without generating"""
        self.do('import model sm')
        shared = self.cmd.do_check_double_counting(
            'double_counting { e+ e- > e+ e- } { e+ e- > z > e+ e- }')
        self.assertEqual(len(shared), 1)
        self.assertRaises(InvalidCmd, self.cmd.do_check_double_counting,
                          'double_counting { e+ e- > e+ e- }')

    def test_check_double_counting_file(self):
        """check double_counting reads named sets from a file"""
        self.do('import model sm')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'sets.txt')
        try:
            with open(path, 'w') as output:
                output.write("""import model sm
define j = g u c d s b u~ c~ d~ s~ b~
set process_name A
generate e+ e- > e+ e-
add process e+ e- > z > e+ e-
set process_name B
generate e+ e- > e+ e-
""")
            shared = self.cmd.do_check_double_counting('double_counting ' + path)
            self.assertEqual(len(shared), 4)
            self.assertEqual(list(shared.values())[0], set(['A', 'B']))
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_file_current(self):
        """file check leaves the first process set as current"""
        self.do('import model sm')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'sets.txt')
        try:
            with open(path, 'w') as output:
                output.write("""import model sm
set process_name A
generate e+ e- > e+ e-
set process_name B
generate mu+ mu- > mu+ mu-
""")
            self.cmd.do_check_double_counting('double_counting ' + path)
            current = [amplitude['process'].nice_string()
                       for amplitude in self.cmd._curr_amps]
            self.assertTrue(any('e+ e- > e+ e-' in name for name in current))
            self.assertFalse(any('mu+ mu-' in name for name in current))
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_file_requires_model(self):
        """file mode does not import a model named by the file"""
        self.cmd._curr_model = None
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'sets.txt')
        try:
            with open(path, 'w') as output:
                output.write("""import model sm
set process_name A
generate e+ e- > e+ e-
""")
            with self.assertRaises(InvalidCmd) as context:
                self.cmd.do_check_double_counting('double_counting ' + path)
            self.assertIn('No model active', str(context.exception))
        finally:
            shutil.rmtree(tmpdir)
            self.do('import model sm')

    def test_check_double_counting_file_errors(self):
        """check double_counting rejects malformed process-set files"""
        self.do('import model sm')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'sets.txt')

        def assert_error(content, message):
            with open(path, 'w') as output:
                output.write(content)
            with self.assertRaises(InvalidCmd) as context:
                self.cmd.do_check_double_counting('double_counting ' + path)
            self.assertIn(message, str(context.exception))

        try:
            assert_error("""import model sm
set process_name A
generate e+ e- > e+ e-
set process_name A
generate e+ e- > mu+ mu-
""", 'two different definitions')
            assert_error("""import model sm
generate e+ e- > e+ e-
""", 'every generate must belong')
            assert_error("""import model sm
set process_name A
generate e+ e- > e+ e-
generate e+ e- > mu+ mu-
""", 'already has a generate')
            assert_error("""import model sm
set process_name A
generate e+ e- > e+ e-
output foo
""", 'unsupported command')
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_multiparticles(self):
        """file multiparticle definitions are announced and restored"""
        self.do('import model sm')
        self.do('define j = u d')
        saved = list(self.cmd._multiparticles['j'])
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'sets.txt')
        try:
            with open(path, 'w') as output:
                output.write("""import model sm
define j = g u c d s b u~ c~ d~ s~ b~
set process_name A
generate e+ e- > e+ e-
set process_name B
generate e+ e- > e+ e-
""")
            with self.assertLogs('cmdprint', level='INFO') as captured:
                self.cmd.do_check_double_counting('double_counting ' + path)
            self.assertTrue(any('redefined in the file' in message
                                for message in captured.output))
            self.assertEqual(self.cmd._multiparticles['j'], saved)
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_decays(self):
        """check double_counting compares production and decay diagrams"""
        self.do('import model sm')
        self.do('generate p p > t t~, t > b w+, t~ > b~ w-')
        shared = self.cmd.do_check_double_counting(
            'double_counting { p p > t t~, t > b w+, t~ > b~ w- }')
        self.assertEqual(len(shared), 7)
        shared = self.cmd.do_check_double_counting(
            'double_counting { p p > t t~, (t > b w+, w+ > e+ ve), t~ > b~ w- }')
        self.assertEqual(len(shared), 0)

    def test_check_double_counting_decay_overlap(self):
        """a decay chain matches the plain diagrams it represents"""
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        shared = self.cmd.do_check_double_counting(
            'double_counting { p p > t t~, t > b w+, t~ > b~ w- }')
        self.assertEqual(len(shared), 7)

    def test_check_double_counting_zz_overlap(self):
        """double-Z diagrams match when the generated set contains them"""
        self.do('import model sm')
        self.do('generate p p > l+ l- u u~ QED<=4 QCD<=2')
        shared = self.cmd.do_check_double_counting(
            'double_counting { p p > z z, z > l+ l-, z > u u~ }')
        self.assertTrue(len(shared) > 0)
        self.assertEqual(list(shared.values())[0], set(['current', 'argument']))

    def test_check_double_counting_show(self):
        """--show selects raw, chain or chain-all output"""
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        command = 'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
        with self.assertLogs('cmdprint', level='INFO') as captured:
            self.cmd.do_check_double_counting(command + '--show=chain')
        chain = '\n'.join(captured.output)
        self.assertIn(' > t t~ > ', chain)
        self.assertNotIn('id:', chain)
        with self.assertLogs('cmdprint', level='INFO') as captured:
            self.cmd.do_check_double_counting(command + '--show=chain-all')
        chain_all = '\n'.join(captured.output)
        self.assertIn(' > g t t~ > ', chain_all)
        with self.assertLogs('cmdprint', level='INFO') as captured:
            self.cmd.do_check_double_counting(command + '--show=raw')
        self.assertIn('id:', '\n'.join(captured.output))
        with self.assertLogs('cmdprint', level='INFO') as captured:
            self.cmd.do_check_double_counting(command + '--show')
        missing = '\n'.join(captured.output)
        self.assertIn('No value was provided for --show', missing)
        self.assertIn('id:', missing)
        self.assertIsNone(self.cmd.do_check(
            'double_counting { p p > w+ w- b b~ }'))
        with self.assertLogs('cmdprint', level='INFO') as captured:
            self.cmd.do_check_double_counting(command + '--show=bogus')
        invalid = '\n'.join(captured.output)
        self.assertIn('Invalid --show value "bogus"', invalid)
        self.assertIn('Available options are: raw, chain, chain-all.', invalid)
        self.assertIn('id:', invalid)

    def test_check_double_counting_bsm_names(self):
        """particle names in the chain come from the active BSM model"""
        self.do('import model MSSM_SLHA2')
        self.do('generate p p > go go')
        with self.assertLogs('cmdprint', level='INFO') as captured:
            shared = self.cmd.do_check_double_counting(
                'double_counting { p p > go go } --show=chain')
        chain = '\n'.join(captured.output)
        self.assertTrue(len(shared) > 0)
        self.assertIn('go', chain)
        self.assertNotIn('1000021', chain)

    def test_check_double_counting_save(self):
        """--save writes the repeated diagrams as a PDF"""
        if not shutil.which('gs'):
            self.skipTest('ghostscript not installed')
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'diagrams', 'dc', 'repeated.pdf')
        try:
            shared = self.cmd.do_check_double_counting(
                'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
                '--save=' + path)
            self.assertEqual(len(shared), 7)
            self.assertTrue(os.path.isfile(path))
            with open(path, 'rb') as handle:
                self.assertEqual(handle.read(4), b'%PDF')
            self.assertGreater(os.path.getsize(path), 1000)
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_default(self):
        """bare --save writes repeated_diagrams.pdf in the current directory"""
        if not shutil.which('gs'):
            self.skipTest('ghostscript not installed')
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        previous = os.getcwd()
        try:
            os.chdir(tmpdir)
            shared = self.cmd.do_check_double_counting(
                'double_counting { p p > t t~, t > b w+, t~ > b~ w- } --save')
            self.assertEqual(len(shared), 7)
            path = os.path.join(tmpdir, 'repeated_diagrams.pdf')
            self.assertTrue(os.path.isfile(path))
            with open(path, 'rb') as handle:
                self.assertEqual(handle.read(4), b'%PDF')
        finally:
            os.chdir(previous)
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_directory(self):
        """--save=DIR uses the default filename inside the directory"""
        if not shutil.which('gs'):
            self.skipTest('ghostscript not installed')
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        target_dir = os.path.join(tmpdir, 'diagrams', 'dc')
        try:
            os.makedirs(target_dir)
            shared = self.cmd.do_check_double_counting(
                'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
                '--save=' + target_dir)
            self.assertEqual(len(shared), 7)
            path = os.path.join(target_dir, 'repeated_diagrams.pdf')
            self.assertTrue(os.path.isfile(path))
            with open(path, 'rb') as handle:
                self.assertEqual(handle.read(4), b'%PDF')
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_non_pdf(self):
        """a non-pdf --save path warns and is ignored"""
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'repeated.txt')
        try:
            with self.assertLogs('cmdprint', level='INFO') as captured:
                shared = self.cmd.do_check_double_counting(
                    'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
                    '--save=' + path)
            self.assertEqual(len(shared), 7)
            self.assertTrue(any('Only .pdf output is supported' in message
                                for message in captured.output))
            self.assertFalse(os.path.exists(path))
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_new_directory(self):
        """--save=DIR/ creates the directory and uses the default filename"""
        if not shutil.which('gs'):
            self.skipTest('ghostscript not installed')
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        target_dir = os.path.join(tmpdir, 'diagrams', 'dc') + os.sep
        try:
            shared = self.cmd.do_check_double_counting(
                'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
                '--save=' + target_dir)
            self.assertEqual(len(shared), 7)
            path = os.path.join(target_dir, 'repeated_diagrams.pdf')
            self.assertTrue(os.path.isfile(path))
            with open(path, 'rb') as handle:
                self.assertEqual(handle.read(4), b'%PDF')
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_existing_file(self):
        """an extensionless existing file warns and is left untouched"""
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'dc')
        try:
            with open(path, 'w') as handle:
                handle.write('keep')
            with self.assertLogs('cmdprint', level='INFO') as captured:
                shared = self.cmd.do_check_double_counting(
                    'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
                    '--save=' + path)
            self.assertEqual(len(shared), 7)
            self.assertTrue(any('Only .pdf output is supported' in message
                                for message in captured.output))
            with open(path) as handle:
                self.assertEqual(handle.read(), 'keep')
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_decay(self):
        """decay-only matches can be saved as a PDF"""
        if not shutil.which('gs'):
            self.skipTest('ghostscript not installed')
        self.do('import model sm')
        self.do('generate p p > t t~, t > b w+, t~ > b~ w-')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'decay.pdf')
        try:
            shared = self.cmd.do_check_double_counting(
                'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
                '--save=' + path)
            self.assertEqual(len(shared), 7)
            self.assertTrue(os.path.isfile(path))
            with open(path, 'rb') as handle:
                self.assertEqual(handle.read(4), b'%PDF')
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_failure_keeps_old(self):
        """a failed ghostscript run leaves the previous PDF untouched"""
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'repeated.pdf')
        try:
            with open(path, 'wb') as handle:
                handle.write(b'old report')
            with mock.patch(
                    'double_counting.subprocess.check_call',
                    side_effect=OSError('ghostscript failed')):
                with self.assertRaises(InvalidCmd):
                    self.cmd.do_check_double_counting(
                        'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
                        '--save=' + path)
            with open(path, 'rb') as handle:
                self.assertEqual(handle.read(), b'old report')
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_save_with_show(self):
        """--save works with --show, including an empty --show value"""
        if not shutil.which('gs'):
            self.skipTest('ghostscript not installed')
        self.do('import model sm')
        self.do('generate p p > w+ w- b b~')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'chain.pdf')
        command = 'double_counting { p p > t t~, t > b w+, t~ > b~ w- } '
        try:
            with self.assertLogs('cmdprint', level='INFO') as captured:
                shared = self.cmd.do_check_double_counting(
                    command + '--show=chain --save=' + path)
            output = '\n'.join(captured.output)
            self.assertEqual(len(shared), 7)
            self.assertIn(' > t t~ > ', output)
            self.assertNotIn('id:', output)
            self.assertTrue(os.path.isfile(path))
            with self.assertLogs('cmdprint', level='INFO') as captured:
                self.cmd.do_check_double_counting(command + '--show=')
            output = '\n'.join(captured.output)
            self.assertIn('No value was provided for --show', output)
            self.assertIn('id:', output)
        finally:
            shutil.rmtree(tmpdir)

    def test_check_double_counting_model(self):
        """a model requested only by the file is reported, not imported"""
        self.do('import model MSSM_SLHA2')
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'sets.txt')
        try:
            with open(path, 'w') as output:
                output.write("""import model sm
set process_name A
generate e+ e- > e+ e-
set process_name B
generate e+ e- > e+ e-
""")
            with self.assertLogs('cmdprint', level='INFO') as captured:
                shared = self.cmd.do_check_double_counting('double_counting ' + path)
            self.assertTrue(any('File requests model "sm"' in message
                                for message in captured.output))
            self.assertTrue(any('MSSM_SLHA2' in message
                                for message in captured.output))
            self.assertTrue(len(shared) > 0)
        finally:
            shutil.rmtree(tmpdir)

