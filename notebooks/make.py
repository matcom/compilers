# coding: utf8

import sys
import os
import json
from pathlib import Path


def split_solution(content):
    solution = dict(cells=[])
    final = dict(cells=[])

    for k,v in content.items():
        if k != 'cells':
            solution[k] = v
            final[k] = v
            continue

    cells = content['cells']

    for cell in cells:
        if cell['cell_type'] != 'code':
            solution['cells'].append(cell)
            final['cells'].append(cell)
            continue

        source = cell['source']

        solution_source = []
        final_source = []

        state = 'normal'

        for line in source:
            if state == 'normal':
                if line.strip().endswith(':solution:'):
                    state = 'solution'
                else:
                    solution_source.append(line)
                    final_source.append(line)

            elif state == 'solution':
                if line.strip().endswith(':final:'):
                    state = 'final'
                else:
                    solution_source.append(line)

            elif state == 'final':
                if line.strip().endswith(':end:'):
                    state = 'normal'
                else:
                    final_source.append(line)

        solution_cell = dict(**cell)
        solution_cell['source'] = solution_source

        solution['cells'].append(solution_cell)

        final_cell = dict(**cell)
        final_cell['source'] = final_source
        final_cell['execution_count'] = None
        final_cell['outputs'] = []

        final['cells'].append(final_cell)

    return solution, final


def main(template_file, final_file, solution_file):
    print(f"Making {template_file}")

    fd = open(template_file)
    content = json.load(fd)

    solution, final = split_solution(content)

    with open(solution_file, 'w') as fd:
        json.dump(solution, fd, indent=1)

    with open(final_file, 'w') as fd:
        json.dump(final, fd, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
