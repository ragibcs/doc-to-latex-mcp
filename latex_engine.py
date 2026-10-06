import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pymupdf as fitz
from skimage.metrics import structural_similarity

from documents import analyze, assets, docx_body, escape_tex, pdf_document, source_file


PREAMBLE = r'''\documentclass{article}
\usepackage{fontspec}
\setmainfont{TeX Gyre Termes}
\setsansfont{TeX Gyre Heros}
\setmonofont{TeX Gyre Cursor}
\usepackage{graphicx,xcolor}
\usepackage[absolute,overlay]{textpos}
\usepackage{pdfpages}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\TPHorizModule}{1bp}
\setlength{\TPVertModule}{1bp}
\textblockorigin{0bp}{0bp}
'''


def generate(job, mode='editable', font_scale=1.0, x_offset=0.0, y_offset=0.0):
    if mode not in ('editable', 'facsimile'):
        raise ValueError('Mode must be editable or facsimile.')
    for value, low, high in [(font_scale, .8, 1.2), (x_offset, -20, 20), (y_offset, -20, 20)]:
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Font scale must be 0.8–1.2; offsets must be -20–20 points.')
    warnings = []
    for stale in ('compiled.pdf', 'main.pdf', 'comparison.json', 'project.zip'):
        (job / stale).unlink(missing_ok=True)
    source = source_file(job)
    if source.suffix == '.docx':
        if mode == 'facsimile':
            raise ValueError('Facsimile mode requires a PDF. Export the DOCX to PDF first.')
        tex = PREAMBLE + '\\usepackage[margin=25mm]{geometry}\n\\begin{document}\n' + docx_body(job) + '\n\\end{document}\n'
        assets(job)
        warnings = ['DOCX flow reconstruction: basic text, headings, and tables only. Images are exported separately; equations, headers, lists, and pagination require review.']
    elif mode == 'facsimile':
        with pdf_document(job):
            pass
        tex = PREAMBLE + '\\begin{document}\n\\includepdf[pages=-,fitpaper=true]{source.pdf}\n\\end{document}\n'
        warnings = ['Facsimile includes the original PDF pages. The visual content is not editable LaTeX.']
    else:
        layout = analyze(job)
        images = assets(job)
        first = layout['pages'][0]
        tex = PREAMBLE + f"\\usepackage[paperwidth={first['width']:.3f}bp,paperheight={first['height']:.3f}bp,margin=0bp]{{geometry}}\n\\begin{{document}}\n"
        for page_index, page in enumerate(layout['pages']):
            if page_index:
                tex += '\\clearpage\n'
            tex += f"\\pdfpagewidth={page['width']:.3f}bp\n\\pdfpageheight={page['height']:.3f}bp\n\\null\n"
            for image in images:
                if image.get('page') != page['page']:
                    continue
                x0, y0, x1, y1 = image['bbox']
                w, h = max(x1 - x0, 1), max(y1 - y0, 1)
                tex += f"\\begin{{textblock*}}{{{w:.3f}bp}}({x0 + x_offset:.3f}bp,{y0 + y_offset:.3f}bp)\\noindent\\includegraphics[width={w:.3f}bp,height={h:.3f}bp]{{{image['file']}}}\\end{{textblock*}}\n"
            for block in page['blocks']:
                for span in block['spans']:
                    text = escape_tex(span['text'])
                    if not text.strip():
                        continue
                    size = max(1, min(200, span['size'] * font_scale))
                    x, y = span['origin']
                    y -= size * .82
                    width = max(page['width'] - x, 20)
                    font = span['font'].lower()
                    family = r'\sffamily' if any(s in font for s in ('arial', 'helvetica', 'sans')) else r'\ttfamily' if any(s in font for s in ('mono', 'courier')) else r'\rmfamily'
                    weight = r'\bfseries' if span['flags'] & 16 else ''
                    italic = r'\itshape' if span['flags'] & 2 else ''
                    color = f"{span.get('color', 0):06X}"[-6:]
                    tex += f'\\begin{{textblock*}}{{{width:.3f}bp}}({x + x_offset:.3f}bp,{y + y_offset:.3f}bp)\\noindent{{{family}{weight}{italic}\\fontsize{{{size:.3f}}}{{{size * 1.2:.3f}}}\\selectfont\\color[HTML]{{{color}}}\\mbox{{{text}}}}}\\end{{textblock*}}\n'
        tex += '\\end{document}\n'
        warnings = ['PDF text and raster images use approximate positions and mapped fonts. Vector art, rotated text, and mathematical glyphs may differ. Tables remain positioned text, not semantic tabular environments.']
    (job / 'main.tex').write_text(tex, encoding='utf-8')
    (job / 'references.bib').write_text('% Bibliography extraction is not automatic. Add verified entries here.\n', encoding='utf-8')
    settings = {'mode': mode, 'font_scale': font_scale, 'x_offset': x_offset, 'y_offset': y_offset, 'warnings': warnings}
    (job / 'generation.json').write_text(json.dumps(settings), encoding='utf-8')
    return {'file': 'main.tex', **settings}


def compile_project(job):
    if not (job / 'main.tex').exists():
        raise ValueError('Call generate_latex first.')
    engine = shutil.which('xelatex')
    if not engine:
        raise RuntimeError('XeLaTeX is not installed. Deploy with the included Dockerfile.')
    (job / 'compiled.pdf').unlink(missing_ok=True)
    (job / 'main.pdf').unlink(missing_ok=True)
    environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(job), 'TMPDIR': str(job), 'openin_any': 'p', 'openout_any': 'p', 'shell_escape': 'f', 'SOURCE_DATE_EPOCH': '1700000000'}
    for _ in range(2):
        with (job / 'compile.log').open('w') as log:
            try:
                result = subprocess.run([engine, '-no-shell-escape', '-interaction=nonstopmode', '-halt-on-error', '-file-line-error', 'main.tex'], cwd=job, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=45)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('Compilation exceeded 45 seconds.') from exc
        if result.returncode:
            tail = (job / 'compile.log').read_text(errors='replace')[-4000:]
            return {'success': False, 'error': 'Compilation failed. Review font/glyph support or use PDF facsimile mode.', 'log_tail': tail}
    if not (job / 'main.pdf').is_file():
        raise RuntimeError('Compiler did not create a PDF.')
    shutil.copyfile(job / 'main.pdf', job / 'compiled.pdf')
    with fitz.open(job / 'compiled.pdf') as doc:
        return {'success': True, 'file': 'compiled.pdf', 'pages': len(doc)}


def compare(job):
    if source_file(job).suffix != '.pdf':
        return {'available': False, 'reason': 'Visual comparison needs an original PDF. DOCX has no fixed rendered baseline.'}
    if not (job / 'compiled.pdf').exists():
        raise ValueError('Compile the generated LaTeX first.')
    pages = []
    with pdf_document(job) as original, fitz.open(job / 'compiled.pdf') as generated:
        for i in range(min(len(original), len(generated))):
            a, b = original[i], generated[i]
            same_size = abs(a.rect.width - b.rect.width) < 1 and abs(a.rect.height - b.rect.height) < 1
            pa = a.get_pixmap(matrix=fitz.Matrix(.75, .75), colorspace=fitz.csGRAY, alpha=False)
            pb = b.get_pixmap(matrix=fitz.Matrix(.75, .75), colorspace=fitz.csGRAY, alpha=False)
            aa = np.frombuffer(pa.samples, dtype=np.uint8).reshape(pa.height, pa.width)
            bb = np.frombuffer(pb.samples, dtype=np.uint8).reshape(pb.height, pb.width)
            if aa.shape != bb.shape:
                pages.append({'page': i + 1, 'ssim': None, 'same_size': False, 'issue': 'Page sizes differ; pixel metrics not comparable.'})
                continue
            ssim = float(structural_similarity(aa, bb, data_range=255))
            difference = float(np.abs(aa.astype(float) - bb.astype(float)).mean() / 255)
            pages.append({'page': i + 1, 'ssim': round(ssim, 5), 'mean_pixel_difference': round(difference, 5), 'same_size': same_size})
        scores = [p['ssim'] for p in pages if p.get('ssim') is not None]
        result = {'available': True, 'original_pages': len(original), 'generated_pages': len(generated), 'page_count_matches': len(original) == len(generated), 'mean_ssim_compared_pages': round(sum(scores) / len(scores), 5) if scores else None, 'pages': pages, 'note': 'SSIM is a raster similarity measure, not a semantic accuracy score. No target fidelity is guaranteed.'}
    (job / 'comparison.json').write_text(json.dumps(result), encoding='utf-8')
    return result
