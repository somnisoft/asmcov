#!/usr/bin/env python3
"""measure coverage of Linux ELF binary using ptrace"""
__license__ = 'SPDX-License-Identifier: CC0-1.0'
import argparse
import ctypes
import dataclasses
import hashlib
import html
import os
import sqlite3
import subprocess
import sys
import webbrowser


class _Ptrace:
    def __init__(self):
        path = os.path.dirname(os.path.realpath(__file__)) + '/asmcovtrace.so'
        self._asmcovtrace = ctypes.cdll.LoadLibrary(path)
        self._asmcovtrace.asmcovtrace_open.argtype = [
            ctypes.POINTER(ctypes.c_char),
            ctypes.POINTER(ctypes.c_char_p)
        ]
        self._asmcovtrace.asmcovtrace_open.restype = ctypes.c_int
        self._asmcovtrace.asmcovtrace_next.argtype = [
            ctypes.c_int
        ]
        self._asmcovtrace.asmcovtrace_next.restype = ctypes.c_ulonglong

    def asmcovtrace_open(self, path, argv):
        """call asmcovtrace_open in asmcovtrace.so"""
        argv = [a.encode() for a in argv]
        argv.append(None)
        argv = (ctypes.c_char_p * len(argv))(*argv)
        return self._asmcovtrace.asmcovtrace_open(path, argv)

    def asmcovtrace_next(self, pid):
        """call asmcovtrace_next in asmcovtrace.so"""
        return self._asmcovtrace.asmcovtrace_next(pid)


@dataclasses.dataclass
class _AsmLine:
    type_: str
    line_number: int
    code: str
    hits: int


class _AsmCovReportHTML:
    def __init__(self, path):
        self._path = path
        self._html = ''

    def generate(self, asm):
        """generate the HTML report and save to file"""
        path_prism = os.path.dirname(os.path.realpath(__file__)) + '/prism'
        path_css = f'{path_prism}/prism.css'
        path_js = f'{path_prism}/prism.js'
        data_lines = []
        asm_html_lines = ''
        prev_asmline = None
        for idx, asmline in enumerate(asm):
            if asmline.type_ == 'instruction' and asmline.hits < 1:
                if prev_asmline and prev_asmline.type_ == 'label':
                    data_lines.append(str(idx))
                data_lines.append(str(idx + 1))
            if asmline.type_ == 'label':
                asmline.code = asmline.code[1:-1] + ':'
            else:
                asmline.code = '\t' + asmline.code
                asmline.code += f' ; hits={str(asmline.hits)}'
            asm_html_lines += html.escape(asmline.code) + '\n'
            prev_asmline = asmline
        data_lines = ','.join(data_lines)
        self._html = '<!DOCTYPE html>\n'
        self._html += '<html lang="en">'
        self._html += '<head>'
        self._html += '<meta charset="utf-8">'
        self._html += '<title>asmcov</title>'
        self._html += f'<link href="{path_css}" rel="stylesheet"/>'
        self._html += '</head>'
        self._html += '<body class="line-highlight">'
        self._html += f'<script src="{path_js}"></script>'
        self._html += '<header>'
        self._html += '<h1>Assembly code coverage generated by asmcov</h1>'
        self._html += '</header>'
        self._html += '<div>'
        self._html += f'<pre class="line-numbers" data-line="{data_lines}">'
        self._html += '<code class="language-nasm">'
        self._html += asm_html_lines
        self._html += '</code>'
        self._html += '</pre>'
        self._html += '</div>'
        self._html += '<footer>'
        self._html += '</footer>'
        self._html += '</body>'
        self._html += '</html>'
        with open(self._path, 'w') as file:
            file.write(self._html)

    def display(self):
        """display the HTML report in the default web browser"""
        abspath = os.path.abspath(self._path)
        url = f'file://{abspath}'
        webbrowser.open(url)


class _AsmCov:
    def __init__(self, args, argv):
        self.exit_code = 0
        self._args = args
        self._argv = argv
        self._ptrace = _Ptrace()
        self._asm = []
        self._db = None
        self._program = {}
        self._load_db()

    def __del__(self):
        self._db.close()

    def run_coverage(self):
        """run the binary and record coverage info"""
        self._get_hash()
        self._get_start_address()
        if self._already_disassembled():
            self._get_disassembly_db()
        else:
            self._get_disassembly_file()
            self._get_disassembly_db()
        self._trace_for_coverage()

    def gen_report(self):
        """generate a report showing line coverage"""
        self._get_hash()
        self._get_start_address()
        self._get_disassembly_db()
        report = _AsmCovReportHTML('asmcov.html')
        report.generate(self._asm)
        report.display()

    def _load_db(self):
        self._db = sqlite3.connect('asmcov.db')
        self._db.execute(
            '''
            CREATE TABLE IF NOT EXISTS program(
                program_id INTEGER PRIMARY KEY,
                hash       TEXT UNIQUE
            )
            '''
        )
        self._db.execute(
            '''
            CREATE TABLE IF NOT EXISTS line(
                line_id     INTEGER PRIMARY KEY,
                program_id  INTEGER,
                type        TEXT,
                line_number INTEGER,
                code        TEXT,
                hits        INTEGER,
                FOREIGN KEY(program_id) REFERENCES program(program_id),
                UNIQUE(program_id, type, line_number)
            )
            '''
        )

    def _get_hash(self):
        with open(self._args.file, 'rb') as file:
            file_data = file.read()
        self._program['hash'] = hashlib.sha256(file_data).hexdigest()
        cursor = self._db.cursor()
        cursor.execute(
            'INSERT INTO program(hash) VALUES(?) ON CONFLICT(hash) DO NOTHING',
            (self._program['hash'],)
        )
        self._db.commit()
        self._program['id'] = self._db.execute(
            'SELECT program_id FROM program WHERE hash = ?',
            (self._program['hash'],)
        ).fetchone()[0]

    def _already_disassembled(self):
        num_lines = self._db.execute(
            '''SELECT COUNT(*)
            FROM line
            WHERE program_id = ?''',
            (self._program['id'],)
        ).fetchone()[0]
        if num_lines > 0:
            return True
        return False

    def _get_start_address(self):
        cmd = ['readelf', '-h', self._args.file]
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            text=True
        )
        for line in result.stdout.split('\n'):
            if 'Entry point address:' in line:
                start_address = line.partition(':')[2].strip()
            elif 'Type:' in line:
                type_ = line.partition(':')[2].strip()
                if not type_.startswith('EXEC'):
                    sys.exit(f'ERROR: unsupported type: {type_}')
        self._program['start_address'] = int(start_address, 16)

    def _get_disassembly_file(self):
        cmd = [
            'objdump',
            '-S',
            '-j', '.text',
            '--start-address', str(self._program['start_address']),
            self._args.file
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            text=True
        )
        for line in result.stdout.split('\n'):
            if not line:
                continue
            if 'Disassembly of section .text' in line:
                continue
            if line.endswith(':'):
                type_ = 'label'
                label_split = line.partition(' ')
                line_number = label_split[0]
                code = label_split[2].rstrip(':')
            else:
                type_ = 'instruction'
                line_split = line.partition(':')
                line_number = line_split[0].lstrip()
                tab_split = line_split[2].split('\t')
                if len(tab_split) < 3:
                    continue
                code = tab_split[2]
            try:
                line_number = int(line_number, 16)
            except ValueError:
                continue
            self._db.execute(
                '''INSERT INTO line(program_id, type, line_number, code, hits)
                VALUES(?, ?, ?, ?, ?)''',
                (self._program['id'], type_, line_number, code, 0)
            )
        self._db.commit()

    def _get_disassembly_db(self):
        asmlines = self._db.execute(
            '''SELECT type, line_number, code, hits
            FROM line WHERE program_id = ?
            ORDER BY line_number ASC, type DESC''',
            (self._program['id'],)
        ).fetchall()
        for asmline in asmlines:
            asmline = _AsmLine(*asmline)
            self._asm.append(asmline)

    def _trace_for_coverage(self):
        pid = self._ptrace.asmcovtrace_open(
            self._args.file.encode(),
            self._argv
        )
        while True:
            rip = self._ptrace.asmcovtrace_next(pid)
            if rip <= 256:
                self.exit_code = rip
                break
            self._db.execute(
                '''UPDATE line SET hits = hits + 1
                WHERE program_id = ?
                AND type = "instruction"
                AND line_number = ?''',
                (self._program['id'], rip)
            )
        self._db.commit()


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-r',
        action='store_true',
        help='generate and display report'
    )
    parser.add_argument(
        'file',
        help='binary to execute'
    )
    args = parser.parse_known_args()
    argv = [args[0].file]
    argv.extend(args[1])
    args = args[0]
    asmcov = _AsmCov(args, argv)
    if args.r:
        asmcov.gen_report()
    else:
        asmcov.run_coverage()
    return asmcov.exit_code


if __name__ == '__main__':
    sys.exit(_main())