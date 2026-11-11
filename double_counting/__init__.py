"""Double-counting checks for MadGraph5_aMC@NLO process sets."""
import copy
import logging
import os
import re
import shutil
import subprocess
import tempfile
from os.path import join as pjoin

import madgraph.core.base_objects as base_objects
import madgraph.core.diagram_generation as diagram_generation
import madgraph.core.drawing as draw_lib
import madgraph.core.helas_objects as helas_objects
import madgraph.iolibs.drawing_eps as draw
from madgraph.interface.madgraph_interface import MadGraphCmd

logger = logging.getLogger('cmdprint')


class DoubleCountingInterface(MadGraphCmd):

    def do_check(self, line):
        args = self.split_arg(line)
        if args and args[0] == 'double_counting':
            self.do_check_double_counting(line)
            return None
        return super(DoubleCountingInterface, self).do_check(line)

    def do_check_double_counting(self, line):
        """Check the Feynman diagrams shared by two process sets."""

        text = line.strip()
        if text.startswith('double_counting'):
            text = text[len('double_counting'):].strip()
        if not text:
            self.help_check()
            raise self.InvalidCmd('check double_counting requires at least one process set')

        def freeze(value):
            if isinstance(value, dict):
                return tuple(sorted((key, freeze(val)) for key, val in value.items()))
            if isinstance(value, (list, tuple)):
                return tuple(freeze(val) for val in value)
            return value

        def diagram_key(diagram, ninitial):
            def link_key(link):
                if link.end_link:
                    return ('e', freeze(link.links[0][0]))
                return ('v', freeze(link.vertex_id[0]),
                        tuple(link_key(sub_link) for sub_link in link.links))
            tag = diagram_generation.DiagramTag(diagram, model=self._curr_model,
                                                ninitial=ninitial)
            return link_key(tag.tag)

        def amplitude_keys(amplitude):
            if isinstance(amplitude, diagram_generation.DecayChainAmplitude):
                productions = {}
                for sub_amplitude in amplitude.get('amplitudes'):
                    productions.update(amplitude_keys(sub_amplitude))
                chains = [amplitude_keys(decay) for decay in
                          amplitude.get('decay_chains')]
                result = {}
                for prod_key, prod_desc in productions.items():
                    if not chains:
                        result[(prod_key, ())] = prod_desc
                        continue
                    combinations = itertools.product(*[list(chain) for chain in chains])
                    for combination in combinations:
                        key = (prod_key, tuple(sorted(combination)))
                        decay_desc = ' ; '.join(chains[index][single]
                                                for index, single in enumerate(combination))
                        result[key] = prod_desc + '  [decays: ' + decay_desc + ']'
                return result

            process = amplitude.get('process')
            if process.get('has_born') is False:
                raise self.InvalidCmd('check double_counting only supports LO tree diagrams')
            ninitial = process.get_ninitial()
            return {(diagram_key(diagram, ninitial), ()): diagram.nice_string()
                    for diagram in (amplitude.get('diagrams') or [])}

        def generate_set(processes):
            amplitudes = diagram_generation.AmplitudeList()
            for process_line in processes:
                for process in [part.strip() for part in process_line.split(' & ')
                                if part.strip()]:
                    procdef, _leftover = self.extract_decay_chain_process(process)
                    multiprocess = diagram_generation.MultiProcess(
                        procdef,
                        collect_mirror_procs=self.options['group_subprocesses'] in ['Auto', True],
                        ignore_six_quark_processes=self.options.get('ignore_six_quark_processes', []),
                        optimize=False)
                    amplitudes.extend(multiprocess.get('amplitudes'))
            return amplitudes

        owners = {}
        descriptions = {}

        def add_set(name, amplitudes):
            keys = {}
            for amplitude in amplitudes:
                keys.update(amplitude_keys(amplitude))
            logger.info('%s: %i process(es), %i diagram(s)' %
                        (name, len(amplitudes), len(keys)))
            for key, description in keys.items():
                owners.setdefault(key, set()).add(name)
                descriptions.setdefault(key, description)

        if os.path.isfile(text) and '>' not in text and '{' not in text:
            header_import = None
            header_defines = []
            blocks = []
            current = None
            with open(text, 'r') as input_file:
                for line_number, raw_line in enumerate(input_file, 1):
                    current_line = raw_line.split('#')[0].strip()
                    if not current_line:
                        continue
                    if current_line.startswith('import model'):
                        if blocks:
                            raise self.InvalidCmd(
                                'Error in %s at line %i: import/define must come before the first process set.'
                                % (text, line_number))
                        header_import = current_line
                    elif current_line.startswith('define '):
                        if blocks:
                            raise self.InvalidCmd(
                                'Error in %s at line %i: import/define must come before the first process set.'
                                % (text, line_number))
                        header_defines.append(current_line)
                    elif current_line.startswith('set '):
                        if not current_line.startswith('set process_name'):
                            raise self.InvalidCmd(
                                'Error in %s at line %i: unknown set option (only "set process_name NAME" is allowed).'
                                % (text, line_number))
                        name = current_line[len('set process_name'):].strip()
                        if name.startswith('='):
                            name = name[1:].strip()
                        if not name:
                            raise self.InvalidCmd(
                                'Error in %s at line %i: missing process set name.'
                                % (text, line_number))
                        current = {'name': name, 'processes': [], 'generated': False}
                        blocks.append(current)
                    elif current_line.startswith('generate '):
                        if current is None:
                            raise self.InvalidCmd(
                                'Error in %s at line %i: every generate must belong to a named set '
                                '(use "set process_name NAME").' % (text, line_number))
                        if current['generated']:
                            raise self.InvalidCmd(
                                'Error in %s at line %i: process set "%s" already has a generate line.'
                                % (text, line_number, current['name']))
                        current['processes'].append(current_line[len('generate '):].strip())
                        current['generated'] = True
                    elif current_line.startswith('add process '):
                        if current is None or not current['generated']:
                            raise self.InvalidCmd(
                                'Error in %s at line %i: "add process" needs a generate line first.'
                                % (text, line_number))
                        current['processes'].append(current_line[len('add process '):].strip())
                    else:
                        raise self.InvalidCmd(
                            'Error in %s at line %i: unsupported command "%s".'
                            % (text, line_number, current_line))

            named_sets = []
            seen = {}
            for block in blocks:
                if not block['generated']:
                    raise self.InvalidCmd('Process set "%s" has no generate line.' % block['name'])
                if block['name'] in seen:
                    first = seen[block['name']]
                    if first['processes'] == block['processes']:
                        logger.warning('duplicate process set "%s" ignored' % block['name'])
                        continue
                    raise self.InvalidCmd(
                        'Process set name "%s" is used for two different definitions:\n'
                        '  first:  %s\n  second: %s' %
                        (block['name'], ' & '.join(first['processes']),
                         ' & '.join(block['processes'])))
                seen[block['name']] = block
                named_sets.append(block)

            if not named_sets:
                raise self.InvalidCmd('No process set found in %s.' % text)

            if not self._curr_model:
                if not header_import:
                    raise self.InvalidCmd(
                        'No model active. Import a model first or add "import model ..." to %s.' % text)
                self.exec_cmd(header_import)
            elif header_import:
                file_model = header_import.split()[2] if len(header_import.split()) > 2 else ''
                session_model = self._curr_model.get('name')
                if file_model and file_model != session_model:
                    logger.warning('File requests model "%s"; using the active session model "%s".' %
                                   (file_model, session_model))

            saved_multiparticles = {name: list(value) for name, value in
                                    self._multiparticles.items()}
            try:
                for define_line in header_defines:
                    name = define_line[len('define '):].split('=')[0].strip()
                    self.do_define(define_line[len('define '):])
                    new_definition = self._multiparticles.get(name)
                    old_definition = saved_multiparticles.get(name)
                    if old_definition is not None and \
                            set(old_definition) != set(new_definition or []):
                        logger.warning('multiparticle "%s" is redefined in the file; '
                                       'using the file definition for this check.' % name)
                for block in named_sets:
                    add_set(block['name'], generate_set(block['processes']))
            finally:
                self._multiparticles = saved_multiparticles

        else:
            if text.startswith('{'):
                groups = []
                index = 0
                while index < len(text):
                    if text[index] == '{':
                        depth = 1
                        end = index + 1
                        while end < len(text) and depth:
                            if text[end] == '{':
                                depth += 1
                            elif text[end] == '}':
                                depth -= 1
                            end += 1
                        if depth:
                            raise self.InvalidCmd('Unbalanced braces in check double_counting.')
                        groups.append(text[index + 1:end - 1].strip())
                        index = end
                    else:
                        if not text[index].isspace():
                            raise self.InvalidCmd(
                                'Text outside the process sets is not allowed; '
                                'use { PROC & ... } { PROC & ... }.')
                        index += 1
                if len(groups) > 2:
                    raise self.InvalidCmd('check double_counting accepts at most two process sets.')
            else:
                groups = [text]

            if len(groups) == 2:
                add_set('A', generate_set([groups[0]]))
                add_set('B', generate_set([groups[1]]))
            else:
                if not self._curr_amps:
                    raise self.InvalidCmd(
                        'No process has been generated. Either generate the first process:\n'
                        '    generate ...\n'
                        '    check double_counting { ... }\n'
                        'or give both process sets:\n'
                        '    check double_counting { ... } { ... }')
                add_set('current', self._curr_amps)
                add_set('argument', generate_set([groups[0]]))

        shared = {key: value for key, value in owners.items() if len(value) > 1}
        if not shared:
            logger.info('No repeated diagrams found across the process sets.')
        else:
            logger.info('%i diagram(s) appear in more than one set:' % len(shared))
            for key in sorted(shared, key=lambda item: descriptions[item]):
                logger.info(descriptions[key])
                logger.info('    found in: ' + ', '.join(sorted(shared[key])))
        return shared



new_interface = DoubleCountingInterface
minimal_mg5amcnlo_version = (3, 8, 0)
maximal_mg5amcnlo_version = (3, 9, 99)
latest_validated_version = (3, 8, 1)
