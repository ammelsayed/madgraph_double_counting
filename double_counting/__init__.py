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
        show = 'raw'
        option = re.search(r'--show(?:=([-\w]*))?', text)
        if option:
            value = option.group(1)
            text = (text[:option.start()] + text[option.end():]).strip()
            if value is None or value == '':
                logger.warning(
                    'No value was provided for --show; using the default "raw".')
            elif value not in ('raw', 'chain', 'chain-all'):
                logger.error(
                    'Invalid --show value "%s". Available options are: raw, chain, chain-all. Using "raw".' % value)
                show = 'raw'
            else:
                show = value
        save_path = None
        if re.search(r'--save\s*=\s*', text):
            save_option = re.search(
                r'--save\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(\S+))', text)
            if not save_option:
                raise self.InvalidCmd('check double_counting requires --save=PATH')
            save_path = next(group for group in save_option.groups() if group)
            text = (text[:save_option.start()] + text[save_option.end():]).strip()
        else:
            save_option = re.search(r'--save\b', text)
            if save_option:
                tail = text[save_option.end():].strip()
                if tail and not tail.startswith(('{', '--')):
                    raise self.InvalidCmd('check double_counting requires --save=PATH')
                save_path = 'repeated_diagrams.pdf'
                text = (text[:save_option.start()] + text[save_option.end():]).strip()
        if not text:
            self.help_check()
            raise self.InvalidCmd('check double_counting requires at least one process set')

        def freeze(value):
            if isinstance(value, dict):
                return tuple(sorted((key, freeze(val)) for key, val in value.items()))
            if isinstance(value, (list, tuple)):
                return tuple(freeze(val) for val in value)
            return value

        def build_graph(vertices, dangling=None):
            last = len(vertices) - 1
            records = []
            for vertex_index, vertex in enumerate(vertices):
                for leg_index, leg in enumerate(vertex.get('legs')):
                    role = 'out' if (vertex_index < last and
                                     leg_index == len(vertex.get('legs')) - 1) else 'in'
                    records.append((vertex_index, leg_index, leg, role))
            edges = {}
            used = set()
            for vertex_index, leg_index, leg, role in records:
                if role != 'out' or (vertex_index, leg_index) == dangling:
                    continue
                triple = (leg.get('number'), leg.get('id'), leg.get('state'))
                match = None
                for other_index, other_leg_index, other, other_role in records:
                    if other_role != 'in' or \
                            (other_index, other_leg_index) in used or \
                            (other_index, other_leg_index) == dangling or \
                            other_index <= vertex_index:
                        continue
                    if (other.get('number'), other.get('id'), other.get('state')) == triple:
                        match = (other_index, other_leg_index)
                        break
                if match is None:
                    continue
                used.add(match)
                edges[(vertex_index, leg_index)] = match
                edges[match] = (vertex_index, leg_index)
            external = [(vertex_index, leg_index)
                        for vertex_index, leg_index, _leg, role in records
                        if role == 'in' and (vertex_index, leg_index) not in used
                        and (vertex_index, leg_index) != dangling]
            return {'vertices': vertices, 'edges': edges,
                    'external': external, 'conn': dangling}

        def graph_key(graph):
            vertices = graph['vertices']
            edges = graph['edges']

            def encode(index, parent_leg, seen):
                children = []
                for leg_index, leg in enumerate(vertices[index].get('legs')):
                    if leg_index == parent_leg:
                        continue
                    if (index, leg_index) in edges:
                        other, other_leg = edges[(index, leg_index)]
                        if other in seen:
                            continue
                        children.append(('v', leg.get('id'),
                                         freeze(leg.get('polarization')),
                                         freeze(leg.get('onium')),
                                         encode(other, other_leg, seen | set([other]))))
                    else:
                        children.append(('e', leg.get('state'), leg.get('id'),
                                         freeze(leg.get('polarization')),
                                         freeze(leg.get('onium'))))
                return (vertices[index].get('id'), tuple(sorted(children)))

            keys = []
            for index, leg_index in graph['external']:
                leg = vertices[index].get('legs')[leg_index]
                keys.append(('r', leg.get('state'), leg.get('id'),
                             freeze(leg.get('polarization')), freeze(leg.get('onium')),
                             encode(index, leg_index, set([index]))))
            if not keys:
                raise self.InvalidCmd('check double_counting found an empty diagram')
            return min(keys)

        def particle_info(pdg):
            try:
                particle = self._curr_model.get_particle(abs(pdg))
            except Exception:
                return str(pdg), False
            if not particle:
                return str(pdg), False
            if pdg < 0 and not particle.get('self_antipart'):
                name = particle.get('antiname') or particle.get('name')
            else:
                name = particle.get('name')
            width = particle.get('width')
            try:
                value = self._curr_model.get('parameter_dict').get(width, width)
                has_width = abs(complex(value)) > 0
            except (TypeError, ValueError):
                has_width = False
            return name or str(pdg), has_width

        def chain_description(graph, show_all=False):
            def ordered_pids(pids):
                groups = {}
                order = []
                for pdg in pids:
                    key = abs(pdg)
                    if key not in groups:
                        groups[key] = []
                        order.append(key)
                    groups[key].append(pdg)
                ordered = []
                for key in order:
                    ordered.extend(sorted(groups[key], key=lambda item: -item))
                return ordered

            vertices = graph['vertices']
            initial = ordered_pids([vertices[index]['legs'][leg].get('id')
                                    for index, leg in graph['external']
                                    if not vertices[index]['legs'][leg].get('state')])
            final = ordered_pids([vertices[index]['legs'][leg].get('id')
                                  for index, leg in graph['external']
                                  if vertices[index]['legs'][leg].get('state')])
            internal = []
            for (index, leg), (other, other_leg) in graph['edges'].items():
                if (index, leg) < (other, other_leg):
                    internal.append(vertices[index]['legs'][leg].get('id'))
            if not show_all:
                internal = [pdg for pdg in internal if particle_info(pdg)[1]]
            internal = ordered_pids(internal)
            parts = [' '.join(particle_info(pdg)[0] for pdg in initial)]
            if internal:
                parts.append(' '.join(particle_info(pdg)[0] for pdg in internal))
            parts.append(' '.join(particle_info(pdg)[0] for pdg in final))
            return ' > '.join(parts)

        def remove_fake_root(vertices, process):
            initial_ids = set(abs(leg.get('id')) for leg in process.get('legs')
                              if not leg.get('state'))
            for index, vertex in enumerate(vertices):
                candidates = [leg for leg in vertex.get('legs')
                              if not leg.get('state') and abs(leg.get('id')) in initial_ids]
                if not candidates:
                    continue
                if len(candidates) > 1:
                    raise self.InvalidCmd(
                        'check double_counting found an ambiguous decay root')
                leg = candidates[0]
                if len(vertex.get('legs')) == 2:
                    other = [other for other in vertex.get('legs')
                             if other is not leg][0]
                    if abs(other.get('id')) == abs(leg.get('id')):
                        del vertices[index]
                        for vertex_index, remaining in enumerate(vertices):
                            for leg_index, candidate in enumerate(remaining.get('legs')):
                                if candidate is other:
                                    return vertices, (vertex_index, leg_index)
                        raise self.InvalidCmd(
                            'check double_counting failed to find the decaying leg')
                for vertex_index, remaining in enumerate(vertices):
                    for leg_index, candidate in enumerate(remaining.get('legs')):
                        if candidate is leg:
                            return vertices, (vertex_index, leg_index)
                raise self.InvalidCmd(
                    'check double_counting failed to find the decaying leg')
            raise self.InvalidCmd('check double_counting failed to find the decaying leg')

        def combine_graphs(production, production_occurrence, decay, decay_occurrence):
            shift = len(production['vertices'])
            vertices = production['vertices'] + decay['vertices']
            edges = dict(production['edges'])
            for (index, leg_index), (other, other_leg) in decay['edges'].items():
                edges[(index + shift, leg_index)] = (other + shift, other_leg)
            external = [occurrence for occurrence in production['external']
                        if occurrence != production_occurrence]
            external += [(index + shift, leg_index)
                         for index, leg_index in decay['external']]
            production_index, production_leg = production_occurrence
            decay_index, decay_leg = decay_occurrence
            decay_index += shift
            edges[(production_index, production_leg)] = (decay_index, decay_leg)
            edges[(decay_index, decay_leg)] = (production_index, production_leg)
            return {'vertices': vertices, 'edges': edges,
                    'external': external, 'conn': None}

        def decay_ids(decay_amplitude):
            ids = set()
            for sub_amplitude in decay_amplitude.get('amplitudes'):
                for leg in sub_amplitude.get('process').get('legs'):
                    if not leg.get('state'):
                        ids.add(leg.get('id'))
            if not ids:
                raise self.InvalidCmd(
                    'check double_counting failed to identify a decaying particle')
            return ids

        def expand_decay(decay_amplitude):
            expanded = []
            for sub_amplitude in decay_amplitude.get('amplitudes'):
                for diagram in (sub_amplitude.get('diagrams') or []):
                    vertices = copy.deepcopy(diagram.get('vertices'))
                    vertices, conn = remove_fake_root(vertices,
                                                      sub_amplitude.get('process'))
                    graphs = [(build_graph(vertices, dangling=conn), [diagram])]
                    for nested in decay_amplitude.get('decay_chains'):
                        nested_ids = decay_ids(nested)
                        nested_graphs = expand_decay(nested)
                        new_graphs = []
                        for graph, drawings in graphs:
                            for occurrence in list(graph['external']):
                                vertex_index, leg_index = occurrence
                                leg = graph['vertices'][vertex_index].get('legs')[leg_index]
                                if leg.get('id') not in nested_ids:
                                    continue
                                for nested_graph, nested_conn, nested_drawings in nested_graphs:
                                    new_graphs.append((
                                        combine_graphs(
                                            copy.deepcopy(graph), occurrence,
                                            copy.deepcopy(nested_graph), nested_conn),
                                        drawings + nested_drawings))
                        graphs = new_graphs
                    for graph, drawings in graphs:
                        graph['conn'] = conn
                        expanded.append((graph, conn, drawings))
            return expanded

        def decay_full_graphs(decay_chain):
            graphs = []
            for sub_amplitude in decay_chain.get('amplitudes'):
                for diagram in (sub_amplitude.get('diagrams') or []):
                    productions = [(build_graph(copy.deepcopy(diagram.get('vertices'))),
                                    [diagram])]
                    for decay in decay_chain.get('decay_chains'):
                        particle_ids = decay_ids(decay)
                        expanded = expand_decay(decay)
                        new_productions = []
                        for production, drawings in productions:
                            for occurrence in list(production['external']):
                                vertex_index, leg_index = occurrence
                                leg = production['vertices'][vertex_index].get('legs')[leg_index]
                                if leg.get('id') not in particle_ids:
                                    continue
                                for decay_graph, decay_conn, decay_drawings in expanded:
                                    new_productions.append((
                                        combine_graphs(
                                            copy.deepcopy(production), occurrence,
                                            copy.deepcopy(decay_graph), decay_conn),
                                        drawings + decay_drawings))
                        productions = new_productions
                    graphs.extend(productions)
            return graphs

        def ensure_tree(amplitude):
            if isinstance(amplitude, diagram_generation.DecayChainAmplitude):
                for sub_amplitude in amplitude.get('amplitudes'):
                    ensure_tree(sub_amplitude)
                for decay in amplitude.get('decay_chains'):
                    ensure_tree(decay)
                return
            process = amplitude.get('process')
            if process.get('has_born') is False:
                raise self.InvalidCmd(
                    'check double_counting only supports LO tree diagrams')
            for diagram in (amplitude.get('diagrams') or []):
                if 'type' in diagram and diagram.get('type') not in (None, 0):
                    raise self.InvalidCmd(
                        'check double_counting only supports LO tree diagrams')

        def amplitude_keys(amplitude):
            ensure_tree(amplitude)
            if isinstance(amplitude, diagram_generation.DecayChainAmplitude):
                names = ' ; '.join(sub.get('process').nice_string()
                                   for sub in amplitude.get('amplitudes'))
                keys = {}
                for graph, drawings in decay_full_graphs(amplitude):
                    keys[graph_key(graph)] = (names + '  [with decays]',
                                              chain_description(graph),
                                              chain_description(graph, True),
                                              ('decay', drawings))
                return keys

            keys = {}
            for diagram in (amplitude.get('diagrams') or []):
                graph = build_graph(copy.deepcopy(diagram.get('vertices')))
                keys[graph_key(graph)] = (diagram.nice_string(),
                                          chain_description(graph),
                                          chain_description(graph, True),
                                          ('plain', [diagram]))
            return keys

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
                if key not in descriptions:
                    descriptions[key] = description
                elif descriptions[key][3][0] != 'plain' and description[3][0] == 'plain':
                    descriptions[key] = description

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
                raise self.InvalidCmd(
                    'No model active. Import a model before running check double_counting.')
            if header_import:
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
                first_amplitudes = None
                for index, block in enumerate(named_sets):
                    amplitudes = generate_set(block['processes'])
                    add_set(block['name'], amplitudes)
                    if index == 0:
                        first_amplitudes = amplitudes
                self._curr_amps = first_amplitudes
                self._curr_proc_defs = base_objects.ProcessDefinitionList()
                self._curr_matrix_elements = helas_objects.HelasMultiProcess()
                self._done_export = None
                self._export_dir = None
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
            display = {'raw': 0, 'chain': 1, 'chain-all': 2}[show]
            for key in sorted(shared, key=lambda item: descriptions[item][0]):
                logger.info(descriptions[key][display])
                logger.info('    found in: ' + ', '.join(sorted(shared[key])))
        if save_path:
            if os.path.isdir(save_path) or save_path.endswith(os.sep):
                save_path = pjoin(save_path, 'repeated_diagrams.pdf')
            else:
                extension = os.path.splitext(save_path)[1]
                if extension.lower() == '.pdf':
                    pass
                elif not extension and not os.path.isfile(save_path):
                    save_path = pjoin(save_path, 'repeated_diagrams.pdf')
                else:
                    logger.warning(
                        'Only .pdf output is supported for --save; ignoring %s.' % save_path)
                    save_path = None
        if save_path:
            if not shared:
                logger.warning('No repeated diagrams to save.')
            else:
                output_pdf = os.path.abspath(save_path)
                output_dir = os.path.dirname(output_pdf)
                try:
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                except OSError as error:
                    raise self.InvalidCmd(
                        'Could not create output directory %s: %s' % (output_dir, error))
                temp_dir = tempfile.mkdtemp()
                temp_pdf = None
                eps_files = []
                try:
                    ordered = sorted(shared, key=lambda item: descriptions[item][0])
                    for index, key in enumerate(ordered):
                        drawings = descriptions[key][3][1]
                        eps_file = pjoin(temp_dir, 'diagram_%04d.eps' % index)
                        legend = 'found in: ' + ', '.join(sorted(shared[key]))
                        legend = legend.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
                        plot = draw.MultiEpsDiagramDrawer(
                            drawings, eps_file, model=self._curr_model, legend=legend)
                        plot.draw(opt=draw_lib.DrawOption())
                        eps_files.append(eps_file)
                    handle, temp_pdf = tempfile.mkstemp(
                        prefix='.repeated_', suffix='.pdf', dir=output_dir or None)
                    os.close(handle)
                    subprocess.check_call(
                        ['gs', '-dBATCH', '-dNOPAUSE', '-q', '-sDEVICE=pdfwrite',
                         '-sOutputFile=' + temp_pdf] + eps_files)
                    os.replace(temp_pdf, output_pdf)
                    temp_pdf = None
                except (OSError, subprocess.CalledProcessError) as error:
                    raise self.InvalidCmd(
                        'Could not save repeated diagrams to %s: %s' % (output_pdf, error))
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    if temp_pdf and os.path.exists(temp_pdf):
                        os.remove(temp_pdf)
                logger.info('Saved repeated diagrams to %s' % output_pdf)
        return shared



new_interface = DoubleCountingInterface
minimal_mg5amcnlo_version = (3, 8, 0)
maximal_mg5amcnlo_version = (3, 9, 99)
latest_validated_version = (3, 8, 1)
