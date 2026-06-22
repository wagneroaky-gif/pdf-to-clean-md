#!/usr/bin/env python3
"""
pdf_to_clean_md.py — Extrai um PDF para Markdown usando pymupdf4llm e aplica
limpeza determinística (sem LLM/sem tokens) sobre o resultado:

  1. Extração com pymupdf4llm (layout-aware; cai em OCR automaticamente
     se a camada de texto do PDF estiver corrompida/com fonte quebrada).
  2. Remoção de blocos "picture text" (texto capturado de imagens/marca
     d'água de fundo via OCR) — o próprio pymupdf4llm já demarca esses
     blocos com tags específicas.
  3. Remoção de cabeçalhos/rodapés de página repetidos (detecção por
     frequência: qualquer linha curta que se repita muitas vezes ao
     longo do documento é tratada como ruído de página, não conteúdo).
  4. Remoção de números de página isolados (ex.: "**8**").
  5. Colapso de linhas em branco consecutivas.

Instalação (uma vez só):
    pip install pymupdf4llm --break-system-packages   # Linux com Python do sistema
    pip install pymupdf4llm                            # demais ambientes

Uso:
    python3 pdf_to_clean_md.py entrada.pdf saida.md

Exemplo:
    python3 pdf_to_clean_md.py nxwpex.pdf nxwpex_limpo.md

Limitações conhecidas (não resolvidas por este script — exigem revisão
manual ou um modelo de IA para o trecho específico):
  - Eventuais títulos de seção que ficam fora de ordem quando colidem
    espacialmente com tabelas/figuras no PDF original (raro: ~1 em
    cada 10-12 seções, pela experiência com este tipo de documento).
  - Padrões de ruído OCR muito específicos de uma fonte/origem de PDF
    podem não ser cobertos pela heurística de frequência abaixo se
    aparecerem poucas vezes (< limiar) ou com texto variável a cada
    ocorrência.
"""
import sys
import re
from collections import Counter

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO POR IDIOMA
# ---------------------------------------------------------------------------
# Tudo que depende do idioma do PDF de origem está centralizado aqui.
# Use --idioma pt|en|es na linha de comando (padrão: pt).
IDIOMAS = {
    'pt': {
        'tesseract_lang': 'por',
        'stopwords': {
            'que', 'de', 'em', 'para', 'com', 'são', 'uma', 'um', 'dos', 'das',
            'por', 'não', 'mais', 'como', 'ou', 'os', 'as', 'no', 'na', 'do',
            'da', 'se', 'ao', 'aos', 'e', 'também', 'quando', 'muito', 'entre',
            'sua', 'seu',
        },
        'caption_words': ['Figura', 'Quadro', 'Tabela'],
        'fonte_word': 'Fonte',
    },
    'en': {
        'tesseract_lang': 'eng',
        'stopwords': {
            'the', 'of', 'in', 'for', 'with', 'are', 'a', 'an', 'and', 'or',
            'to', 'is', 'on', 'as', 'by', 'that', 'this', 'be', 'it', 'at',
            'from', 'when', 'between', 'your', 'its', 'not', 'can', 'will',
        },
        'caption_words': ['Figure', 'Table'],
        'fonte_word': 'Source',
    },
    'es': {
        'tesseract_lang': 'spa',
        'stopwords': {
            'que', 'de', 'en', 'para', 'con', 'son', 'una', 'un', 'los', 'las',
            'por', 'no', 'más', 'como', 'o', 'es', 'al', 'del', 'se', 'su',
            'sus', 'también', 'cuando', 'muy', 'entre', 'y',
        },
        'caption_words': ['Figura', 'Tabla', 'Cuadro'],
        'fonte_word': 'Fuente',
    },
}

IDIOMA_ATUAL = 'pt'  # alterado em tempo de execução por main() conforme --idioma


def cfg():
    """Atalho para acessar a configuração do idioma selecionado."""
    return IDIOMAS[IDIOMA_ATUAL]
# ---------------------------------------------------------------------------


FREQ_THRESHOLD = 4      # nº mínimo de repetições para considerar "ruído de página"
MAX_HEADER_LEN = 90     # só considera candidatas a cabeçalho/rodapé linhas até este tamanho

# ---------------------------------------------------------------------------
# CALIBRAÇÃO MANUAL (opcional): alguns PDFs com marca d'água translúcida
# fazem o OCR "ler" lixo embutido NO MEIO de uma linha de conteúdo real
# (não como linha isolada repetida) — esse tipo de ruído não é detectável
# por frequência sem risco de apagar texto legítimo. Rode o script uma vez,
# confira o resultado, e se sobrar algum padrão de lixo, adicione aqui como
# regex. Exemplo real encontrado em um documento SENAI/Bureau Veritas:
#
EXTRA_NOISE_PATTERNS = [
    r'\s*mae VU S = <Sy 2c 0ao -_est \*\*\d+\*\* UAAZAUA zi 2eATIAAV p',
]
# ---------------------------------------------------------------------------


MIN_STOPWORD_HITS = 3  # nº mínimo de stopwords reconhecidas para considerar "texto real"


def is_real_content(block_text: str) -> bool:
    """Distingue texto real (ex.: conteúdo OCR de uma caixa/diagrama colorido)
    de ruído de OCR sobre marca d'água/logotipo, pela densidade de palavras
    funcionais comuns do idioma selecionado. Texto corrido tende a ter
    várias; ruído de OCR sobre imagens decorativas praticamente nunca forma
    frases."""
    text = block_text.replace('<br>', ' ')
    words = re.findall(r"[A-Za-zÀ-ÿ]+", text.lower())
    hits = sum(1 for w in words if w in cfg()['stopwords'])
    return hits >= MIN_STOPWORD_HITS


def strip_picture_blocks(text: str) -> str:
    """Remove blocos delimitados pelo pymupdf4llm como texto extraído de imagens
    — MAS preserva o conteúdo se a heurística indicar que é texto real (ex.:
    rótulos dentro de caixas/diagramas coloridos), removendo apenas o ruído
    de fato (OCR de marca d'água/logotipo sobre imagens decorativas)."""

    def _handle_block(match):
        inner = match.group(1)
        if is_real_content(inner):
            # mantém o conteúdo; cada <br> vira uma quebra de linha REAL
            # (antes virava espaço, o que colapsava listas/índices OCR'ados
            # de dentro de caixas/gráficos — ex.: um ÍNDICE com 6 itens —
            # em uma única linha corrida)
            cleaned = re.sub(r'<br>\s*', '\n', inner).strip()
            return cleaned + '\n\n'
        return ''  # descarta: ruído de OCR sobre imagem decorativa

    text = re.sub(
        r'\*\*----- Start of picture text -----\*\*(.*?)\*\*----- End of picture text -----\*\*<br>\n*',
        _handle_block, text, flags=re.DOTALL
    )
    text = re.sub(r'\*\*==> picture \[.*?\] intentionally omitted <==\*\*\n*', '', text)
    return text


def detect_repeated_lines(lines):
    """Detecta linhas curtas que se repetem com alta frequência —
    candidatas a cabeçalho/rodapé de página, não conteúdo real."""
    counts = Counter(l.strip() for l in lines if l.strip())
    return {
        line for line, n in counts.items()
        if n >= FREQ_THRESHOLD and len(line) <= MAX_HEADER_LEN
    }


def is_bare_page_number(line: str) -> bool:
    """Detecta números de página isolados, em algarismos arábicos ou
    romanos, com ou sem marcação Markdown em negrito (ex.: '8', '**8**',
    '**II**'). Numerais romanos de 1 caractere ('I') são deliberadamente
    EXCLUÍDOS por ambiguidade (poderia ser uma palavra/letra real em
    algum idioma) — só remove romanos com 2+ caracteres."""
    s = line.strip()
    if re.fullmatch(r'\*{0,2}\d{1,4}\*{0,2}', s):
        return True
    m = re.fullmatch(r'\*{0,2}([IVXLCDM]{2,8})\*{0,2}', s)
    if m:
        return True
    return False


def remover_numeros_pagina_em_heading(texto: str) -> str:
    """Cobre o caso em que um número de página solto foi erroneamente
    promovido a heading pelo extrator (ex.: '## **20**') — diferente do
    caso tratado por is_bare_page_number, que só olha linhas comuns."""
    linhas = texto.split('\n')
    saida = []
    for l in linhas:
        m = re.match(r'^#{1,6}\s+(.*)$', l)
        if m and is_bare_page_number(m.group(1)):
            continue
        saida.append(l)
    return '\n'.join(saida)


def limpar_resíduos_celulas_tabela(texto: str) -> str:
    """Limpeza defensiva e bem específica: em alguns ambientes (observado no
    Windows, não reproduzido no Linux), o pymupdf4llm gera células de tabela
    com um token curto residual colado no final (ex.: '0,90 a 0,91 282',
    'ATIVIDADE DE ÁGUA MÍNIMA** 444') — aparentemente ligado aos avisos
    'No common ancestor in structure tree' do MuPDF durante a extração.

    Esta função só atua DENTRO de linhas de tabela markdown (começando com
    '|') e só remove o token final se ele for "ruído" reconhecível: todo em
    maiúsculas e/ou dígitos, com no máximo 4 caracteres — para não arriscar
    apagar palavras reais do conteúdo (que normalmente teriam letras
    minúsculas comuns do português).

    NUNCA generalizar isso para remover uma CÉLULA INTEIRA que seja só
    dígitos/maiúsculas curtas (já tentei — ver histórico). Tabelas técnicas
    legítimas (ex.: especificação de pacotes/protocolos com colunas de
    valores hex como 'ff', '0b', '1') têm exatamente esse formato em
    células reais, e uma checagem de célula inteira apaga dado real em
    massa. Esta função deve continuar restrita a remover só um SUFIXO
    colado ao final de uma célula com conteúdo substancial antes dele."""

    def _limpar_linha_tabela(match):
        linha = match.group(0)
        celulas = linha.split('|')
        novas = []
        for celula in celulas:
            nova = re.sub(
                r'(?<=[0-9%,\*])\s+([A-Z0-9]{1,3}(?:\s[A-Z0-9]{1,2})?)\s*$',
                '', celula
            )
            novas.append(nova)
        return '|'.join(novas)

    linhas = texto.splitlines()
    for i, l in enumerate(linhas):
        if l.strip().startswith('|'):
            linhas[i] = _limpar_linha_tabela(re.match(r'.*', l))
    return '\n'.join(linhas)


def collapse_blank_lines(lines):
    out, prev_blank = [], False
    for l in lines:
        is_blank = not l.strip()
        if is_blank and prev_blank:
            continue
        out.append(l)
        prev_blank = is_blank
    return out


def resolver_br_residual(texto: str) -> str:
    """Trata tags <br> que sobraram fora dos blocos já tratados (observado
    em alguns ambientes/versões de OCR como artefato de tabela). Dentro de
    uma linha de tabela markdown (começa com '|') vira espaço — uma quebra
    de linha literal ali quebraria a sintaxe da tabela. Em qualquer outro
    lugar vira uma quebra de linha REAL, preservando a estrutura original
    (ex.: itens de uma lista/índice que ainda tinham <br> remanescente)."""
    linhas_saida = []
    for l in texto.split('\n'):
        if l.strip().startswith('|'):
            linhas_saida.append(re.sub(r'<br>\s*', ' ', l))
        else:
            linhas_saida.extend(re.split(r'<br>\s*', l))
    return '\n'.join(linhas_saida)


TOC_ENTRY_BOUNDARY_RE = re.compile(r'\.{3,}\s*\d{1,4}')


def separar_entradas_indice_coladas(texto: str) -> str:
    """Caso especial (não envolve tags <br>): em páginas de Índice/Sumário
    com líder pontilhado (ex.: '1. INTRODUÇÃO .......... 3'), o próprio
    pymupdf4llm às vezes funde TODAS as entradas numa única linha corrida
    já na extração bruta — antes de qualquer limpeza nossa — porque o
    leiaute pontilhado confunde a reconstrução de parágrafos dele.

    Esta função separa cada entrada em sua própria linha, quebrando logo
    APÓS qualquer 'líder de pontos (3+) + número de página' — esse padrão,
    sozinho, já marca o fim de uma entrada de sumário, então funciona
    independente de como a PRÓXIMA entrada começa: numerada ('1. Título'),
    com prefixo de capítulo ('Chapter 1. Título') ou sem numeração nenhuma
    ('Overview', 'Packing List'). A versão anterior só reconhecia o
    primeiro formato (exigia que a próxima entrada começasse com 'N. '),
    e por isso não separava sumários como o de manuais em inglês que usam
    'Chapter N.' ou títulos de subseção sem número.

    Critério propositalmente restrito ao líder pontilhado (3+ pontos) para
    não arriscar quebrar texto corrido comum que por acaso tenha números
    em sequência (ex.: reticências '...' seguidas de um número isolado)."""
    linhas = texto.split('\n')
    saida = []
    for l in linhas:
        nova = TOC_ENTRY_BOUNDARY_RE.sub(lambda m: m.group(0) + '\n', l)
        # remove o espaço residual que sobra no início de cada linha nova
        # (a entrada seguinte normalmente vinha separada só por um espaço)
        partes = [p[1:] if p.startswith(' ') else p for p in nova.split('\n')]
        saida.extend(partes)
    return '\n'.join(saida)


# ---------------------------------------------------------------------------
# CORREÇÃO DE HEADINGS (estrutura de títulos)
# ---------------------------------------------------------------------------
# Em alguns documentos, o pymupdf4llm (especialmente no caminho via OCR)
# erra a detecção de títulos de duas formas opostas:
#   a) promove texto que não é título (ex.: um nome de pessoa numa tabela
#      de créditos, ou uma linha "Fonte: ...") ao nível de heading "## ";
#   b) deixa de promover um título real, que fica "colado" ao fim do
#      parágrafo anterior em negrito, sem virar uma linha "## " própria.
# As funções abaixo corrigem os dois casos com critérios bem específicos,
# para minimizar o risco de alterar conteúdo que já está correto.

def demover_headings_fonte(texto: str) -> str:
    """Linhas 'Fonte:'/'Source:'/'Fuente:' (conforme idioma) nunca deveriam
    ser headings — são citações."""
    palavra = re.escape(cfg()['fonte_word'])
    return re.sub(
        rf'^#{{1,6}}\s+(\**\s*{palavra}\s*:.*)$', r'\1',
        texto, flags=re.IGNORECASE | re.MULTILINE
    )


def demover_headings_orfas(texto: str) -> str:
    """Demove (rebaixa a texto comum) um heading ÓRFÃO ISOLADO: um único
    heading sem nenhum corpo de texto entre ele e os headings vizinhos dos
    dois lados, mas onde ESSES vizinhos têm corpo próprio — sintoma de que
    esse heading isolado é, na verdade, um valor associado ao heading
    anterior (ex.: um nome de pessoa numa tabela de créditos), não um
    título de seção novo.

    Deliberadamente conservadora: NÃO mexe em cadeias longas de 3+ headings
    consecutivos sem corpo entre si (ex.: uma tabela de créditos inteira
    mal interpretada) — nesses casos não há como distinguir com segurança
    qual item é rótulo e qual é valor sem risco de demover o heading
    errado, então a cadeia é deixada como está para revisão manual."""
    linhas = texto.split('\n')
    idx_headings = [i for i, l in enumerate(linhas) if re.match(r'^#{1,6}\s', l)]

    def tem_corpo_entre(a, b):
        return any(l.strip() for l in linhas[a + 1:b])

    a_demover = []
    for j in range(1, len(idx_headings) - 1):
        anterior, atual, proximo = idx_headings[j - 1], idx_headings[j], idx_headings[j + 1]
        sem_corpo_antes = not tem_corpo_entre(anterior, atual)
        corpo_antes_do_anterior = (j - 2 < 0) or tem_corpo_entre(idx_headings[j - 2], anterior)
        corpo_depois_do_proximo = (j + 2 >= len(idx_headings)) or tem_corpo_entre(proximo, idx_headings[j + 2])
        if sem_corpo_antes and corpo_antes_do_anterior and corpo_depois_do_proximo:
            a_demover.append(atual)

    for i in a_demover:
        linhas[i] = re.sub(r'^#{1,6}\s+', '', linhas[i])
    return '\n'.join(linhas)


def promover_headings_colados(texto: str, nivel: str = '##') -> str:
    """Identifica títulos que ficaram colados em negrito no FIM de um
    parágrafo (em vez de virarem sua própria linha de heading) e os move
    para uma linha de heading própria, antes do parágrafo seguinte.

    Critério de segurança: só promove se as duas primeiras palavras do
    trecho em negrito também forem as duas primeiras palavras do próximo
    parágrafo — sinal forte de que aquele negrito é, de fato, o título
    do parágrafo seguinte (ex.: '...cayetanensis. **Giardia lamblia**'
    seguido de 'Giardia lamblia (intestinalis) é um protozoário...')."""
    linhas = texto.split('\n')
    saida = []
    i = 0
    while i < len(linhas):
        linha = linhas[i]
        ja_e_heading = bool(re.match(r'^#{1,6}\s', linha))
        m = None if ja_e_heading else re.match(r'^(.*\S)\s+\*\*([A-ZÀ-Ý][^*]{2,60})\*\*\s*$', linha)
        if m:
            antes, titulo_candidato = m.group(1), m.group(2)
            j = i + 1
            while j < len(linhas) and not linhas[j].strip():
                j += 1
            proximo = linhas[j].strip() if j < len(linhas) else ''
            palavras_titulo = ' '.join(titulo_candidato.split()[:2]).lower()
            palavras_proximo = ' '.join(proximo.split()[:2]).lower()
            if palavras_titulo and palavras_titulo == palavras_proximo:
                saida.append(antes)
                saida.append('')
                saida.append(f'{nivel} **{titulo_candidato}**')
                i += 1
                continue
        saida.append(linha)
        i += 1
    return '\n'.join(saida)


def _normalizar_para_prefixo(linha: str) -> str:
    return re.sub(r'^[#*\s]+', '', linha.strip())


CABECALHO_NUMERADO_RE = re.compile(r'^\|\s*\d+\s*-\s*[^|]+$')
CABECALHO_NUMERADO_RE2 = re.compile(r'^\d{1,2} {2,}[A-ZÀ-ÿ¡¿].+$')


def remover_cabecalhos_numerados_estruturais(texto: str, limiar: int = 4) -> str:
    """Detecta cabeçalhos de página no formato '| N - Nome do Capítulo' —
    comuns em manuais técnicos — que mudam de texto a cada página (porque
    incluem o título do capítulo atual) e por isso escapam tanto da
    detecção por linha exata quanto por prefixo longo. A detecção aqui é
    pelo FORMATO da linha (regex), não pelo conteúdo, então funciona em
    qualquer idioma sem necessidade de calibração. Só remove se esse
    formato aparecer com frequência alta (>= limiar) no documento, para
    não arriscar apagar uma linha de tabela legítima que coincida."""
    linhas = texto.split('\n')

    candidatas = [l for l in linhas if CABECALHO_NUMERADO_RE.match(l.strip())]
    if len(candidatas) >= limiar:
        linhas = [l for l in linhas if not CABECALHO_NUMERADO_RE.match(l.strip())]

    # Variante 2: "NN  Nome do Capítulo" (sem pipe, separado por 2+ espaços).
    # Padrão mais específico (exige número de 1-2 dígitos + 2+ espaços +
    # maiúscula), então um limiar menor já é seguro o suficiente.
    candidatas2 = [l for l in linhas if CABECALHO_NUMERADO_RE2.match(l.strip())]
    if len(candidatas2) >= 2:
        linhas = [l for l in linhas if not CABECALHO_NUMERADO_RE2.match(l.strip())]

    return '\n'.join(linhas)


def detectar_prefixos_repetidos(linhas, prefixo_len: int = 35, limiar: int = 4):
    """Como detect_repeated_lines, mas agrupa por PREFIXO (não pela linha
    inteira) — necessário porque cabeçalhos/rodapés de página às vezes vêm
    com lixo de OCR variável grudado no final (diferente a cada página),
    fazendo cada ocorrência parecer uma linha distinta e nunca atingir o
    limiar de frequência por igualdade exata."""
    counts = Counter()
    for l in linhas:
        s = _normalizar_para_prefixo(l)
        if len(s) >= prefixo_len:
            counts[s[:prefixo_len]] += 1
    return {p for p, n in counts.items() if n >= limiar}


def remover_cabecalhos_residuais_por_prefixo(texto: str, prefixos_repetidos: set, prefixo_len: int = 35) -> str:
    """Remove qualquer linha cujo início normalizado bata com um dos
    prefixos identificados como cabeçalho/rodapé repetido no documento."""
    if not prefixos_repetidos:
        return texto
    linhas = texto.split('\n')
    saida = []
    for l in linhas:
        s = _normalizar_para_prefixo(l)
        if len(s) >= prefixo_len and s[:prefixo_len] in prefixos_repetidos:
            continue
        saida.append(l)
    return '\n'.join(saida)


def _normalizar_para_sufixo(linha: str) -> str:
    """Remove um número de página (e separador comum: '|', '-', ':') do
    INÍCIO da linha — necessário para detectar rodapés do tipo
    'N | NOVIEMBRE 2021' / 'N - Novembro 2021', em que o número que muda
    a cada página vem ANTES do texto fixo (diferente do cabeçalho tratado
    por detectar_prefixos_repetidos, em que o trecho fixo vem primeiro).

    CUIDADO (bug real encontrado e corrigido): sem o lookahead negativo
    '(?!\\.\\s)', esta função também capturava itens de LISTA NUMERADA
    ('1. Primeiro passo...', '2. Segundo passo...') como se fossem número
    de página + rodapé — e, como vários procedimentos de um mesmo manual
    frequentemente começam com a mesma instrução (ex.: 'On the homepage,
    click Setting...'), isso fazia passos reais e legítimos de instruções
    diferentes serem tratados como 'rodapé repetido' e apagados do
    documento. Confirmado com um caso real: 5 ocorrências legítimas de um
    mesmo primeiro/segundo passo, em procedimentos diferentes, foram
    reduzidas a zero. O lookahead impede o match quando o número é seguido
    de '. ' (ponto + espaço — a convenção universal de lista ordenada),
    preservando o comportamento original só para números de página de
    verdade (que não usam essa convenção)."""
    s = linha.strip()
    s = re.sub(r'^\**\d{1,4}\**(?!\.\s)\s*[\|\-–—:]?\s*', '', s)
    return s


def detectar_sufixos_repetidos(linhas, sufixo_min_len: int = 6, limiar: int = FREQ_THRESHOLD):
    """Como detectar_prefixos_repetidos, mas pela parte FINAL da linha
    (após remover um eventual número de página inicial) — cobre rodapés
    curtos do tipo 'N | NOVIEMBRE 2021', que escapam de detect_repeated_lines
    (porque o número muda, então a linha nunca é idêntica duas vezes) e
    também de detectar_prefixos_repetidos (que exige 35+ caracteres e olha
    o início da linha, não o fim)."""
    counts = Counter()
    for l in linhas:
        if len(l.strip()) > MAX_HEADER_LEN:
            continue
        s = _normalizar_para_sufixo(l)
        if len(s) >= sufixo_min_len:
            counts[s] += 1
    return {s for s, n in counts.items() if n >= limiar}


def remover_rodapes_por_sufixo(texto: str, sufixos_repetidos: set) -> str:
    """Remove linhas curtas cujo conteúdo (após tirar um eventual número de
    página inicial) bata com um dos sufixos identificados como rodapé
    repetido no documento (ex.: '4 | NOVIEMBRE 2021', '5 | NOVIEMBRE 2021',
    ... todas viram 'NOVIEMBRE 2021' após normalizar, e são removidas)."""
    if not sufixos_repetidos:
        return texto
    linhas = texto.split('\n')
    saida = []
    for l in linhas:
        if len(l.strip()) <= MAX_HEADER_LEN and _normalizar_para_sufixo(l) in sufixos_repetidos:
            continue
        saida.append(l)
    return '\n'.join(saida)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# MESCLAGEM AUTOMÁTICA (.md + OCR de página inteira)
# ---------------------------------------------------------------------------
# Insere no .md principal o conteúdo de caixas/figuras que o pymupdf4llm
# capturou de forma incompleta, usando o OCR de página inteira como fonte.
# Critério de segurança: só substitui o trecho de uma figura/quadro se o
# OCR daquela MESMA figura tiver claramente mais conteúdo (limiar abaixo) —
# isso evita inserir duplicatas ou lixo quando o .md já está completo.
def CAPTION_RE():
    palavras = '|'.join(re.escape(w) for w in cfg()['caption_words'])
    return re.compile(rf'^\**\s*({palavras})[\s-]*\d*\s*:?.*$', re.IGNORECASE | re.MULTILINE)


def FONTE_RE():
    palavra = re.escape(cfg()['fonte_word'])
    return re.compile(rf'^\**\s*{palavra}\s*:', re.IGNORECASE | re.MULTILINE)


HEADING_RE = re.compile(r'^#{1,6}\s', re.MULTILINE)

MERGE_RATIO_THRESHOLD = 1.3   # OCR precisa ter pelo menos 30% mais palavras de conteúdo
MERGE_MIN_NEW_WORDS = 5       # e pelo menos 5 palavras novas em termos absolutos


def palavras_de_conteudo(texto: str):
    palavras = re.findall(r"[A-Za-zÀ-ÿ]+", texto.lower())
    return [w for w in palavras if w not in cfg()['stopwords'] and len(w) > 2]


def _proximo_limite(texto: str, pos: int) -> int:
    """Encontra onde um bloco de figura/quadro termina: na próxima linha
    'Fonte:'/'Source:'/'Fuente:', no próximo heading, ou no fim do texto —
    o que vier primeiro."""
    candidatos = []
    m = FONTE_RE().search(texto, pos)
    if m:
        candidatos.append(m.end())
    m = HEADING_RE.search(texto, pos)
    if m:
        candidatos.append(m.start())
    candidatos.append(len(texto))
    return min(candidatos)


def extrair_blocos_legenda(texto: str):
    """Retorna lista de (numero_figura_normalizado, start, end, span_text)
    para cada ocorrência de legenda (Figura/Quadro, Figure/Table, etc.,
    conforme o idioma selecionado) no texto."""
    blocos = []
    for m in CAPTION_RE().finditer(texto):
        numero = re.search(r'\d+', m.group(0))
        chave = numero.group(0) if numero else m.group(0).strip().lower()
        fim = _proximo_limite(texto, m.end())
        blocos.append({
            'chave': (m.group(1).lower(), chave),
            'start': m.start(),
            'end': fim,
            'span': texto[m.start():fim],
        })
    return blocos


def mesclar_pagina(pagina_md: str, pagina_ocr: str) -> str:
    """Para cada figura/quadro do .md desta página, compara com o trecho
    correspondente do OCR de página inteira; se o OCR tiver claramente
    mais conteúdo, substitui o trecho do .md por uma versão marcada para
    revisão, preservando a linha 'Fonte:' original."""
    if not pagina_ocr.strip():
        return pagina_md

    blocos_md = extrair_blocos_legenda(pagina_md)
    blocos_ocr = extrair_blocos_legenda(pagina_ocr)
    ocr_por_chave = {b['chave']: b for b in blocos_ocr}

    # processar de trás para frente para não invalidar os índices ao substituir
    resultado = pagina_md
    for bloco in sorted(blocos_md, key=lambda b: b['start'], reverse=True):
        correspondente = ocr_por_chave.get(bloco['chave'])
        if not correspondente:
            continue

        palavras_md = set(palavras_de_conteudo(bloco['span']))
        palavras_ocr_set = set(palavras_de_conteudo(correspondente['span']))
        n_md, n_ocr = len(palavras_md), len(palavras_ocr_set)
        novas = len(palavras_ocr_set - palavras_md)

        if n_md == 0:
            continue  # nada para comparar com segurança
        if n_ocr < n_md * MERGE_RATIO_THRESHOLD or novas < MERGE_MIN_NEW_WORDS:
            continue  # OCR não traz conteúdo suficientemente novo — não mexe

        # monta o trecho de substituição: legenda original + corpo do OCR
        # marcado para revisão + linha "Fonte:" original (se existia)
        fonte_match = FONTE_RE().search(bloco['span'])
        fonte_linha = bloco['span'][fonte_match.start():].splitlines()[0] if fonte_match else ''
        corpo_ocr = correspondente['span']
        if fonte_match:
            corpo_ocr = corpo_ocr[:FONTE_RE().search(corpo_ocr).start()] if FONTE_RE().search(corpo_ocr) else corpo_ocr

        substituto = (
            f"{bloco['span'][:bloco['span'].find(chr(10)) if chr(10) in bloco['span'] else len(bloco['span'])]}\n\n"
            f"> ⚠️ **Conteúdo recuperado via OCR de página inteira — revisar contra o PDF original "
            f"(colunas/caixas podem estar fora de ordem):**\n>\n"
            f"> {corpo_ocr.strip().replace(chr(10), chr(10) + '> ')}\n\n"
            f"{fonte_linha}"
        )

        resultado = resultado[:bloco['start']] + substituto + resultado[bloco['end']:]

    return resultado
# ---------------------------------------------------------------------------


def strip_extra_noise(text: str) -> str:
    for pattern in EXTRA_NOISE_PATTERNS:
        text = re.sub(pattern, '', text)
    return text


def limpar(raw_text: str, repeated_override=None) -> str:
    """ETAPA 2 do fluxo: aplica a limpeza determinística (sem IA) sobre o
    Markdown bruto retornado pela ETAPA 1 — remove blocos de imagem/OCR-
    -garbage, ruído extra calibrado, cabeçalhos/rodapés repetidos, números
    de página isolados, e colapsa linhas em branco consecutivas.

    Se `repeated_override` for fornecido (conjunto de linhas), usa-o em vez
    de recalcular a detecção de frequência — necessário ao limpar página
    por página, onde a frequência precisa ser calculada no documento
    inteiro, não isoladamente em cada página."""
    text = strip_picture_blocks(raw_text)
    text = strip_extra_noise(text)
    lines = text.splitlines()

    repeated = repeated_override if repeated_override is not None else detect_repeated_lines(lines)

    out = []
    for l in lines:
        s = l.strip()
        if not s:
            out.append(l)
            continue
        if s in repeated:
            continue
        if is_bare_page_number(s):
            continue
        out.append(l)

    out = collapse_blank_lines(out)
    texto_final = '\n'.join(out)
    # defesa extra: tags <br> não deveriam sobrar fora de blocos já tratados
    # (observado em alguns ambientes/versões de OCR como artefato de
    # tabela). Vira espaço dentro de linha de tabela (preserva a sintaxe);
    # fora de tabela vira quebra de linha real (preserva listas/índices).
    texto_final = resolver_br_residual(texto_final)
    texto_final = limpar_resíduos_celulas_tabela(texto_final)
    texto_final = demover_headings_fonte(texto_final)
    texto_final = demover_headings_orfas(texto_final)
    texto_final = promover_headings_colados(texto_final)
    texto_final = separar_entradas_indice_coladas(texto_final)
    return texto_final


def _configurar_tesseract():
    """Tenta localizar o executável do Tesseract automaticamente, sem exigir
    edição manual do script. Primeiro verifica se já está no PATH; se não
    estiver, procura nos locais de instalação padrão do Windows."""
    import shutil
    import pytesseract

    if shutil.which('tesseract'):
        return  # já está no PATH, pytesseract encontra sozinho

    caminhos_comuns_windows = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    ]
    for caminho in caminhos_comuns_windows:
        if __import__('os').path.isfile(caminho):
            pytesseract.pytesseract.tesseract_cmd = caminho
            return

    # não encontrado em nenhum local conhecido — deixa como está;
    # o erro será reportado de forma clara na hora do uso (image_to_string)


def ocr_paginas_completas(caminho_pdf: str, dpi: int = 300):
    """Rede de segurança para conteúdo perdido pelo pymupdf4llm: faz OCR da
    PÁGINA INTEIRA (sem recortar em sub-regiões) com Tesseract diretamente.

    Por quê: em páginas com várias caixas/infográficos coloridos lado a
    lado, o pymupdf4llm às vezes recorta cada caixa como uma região de
    imagem separada para fazer OCR, e esse recorte ocasionalmente perde
    o conteúdo de uma ou mais caixas (testado e confirmado em casos reais).
    Rodar o OCR na página inteira, de uma vez, evita esse recorte e tende
    a capturar todo o texto visível — mas perde a formatação estruturada
    (títulos, negrito etc.) que o pymupdf4llm oferece, e em layouts com
    várias colunas lado a lado o texto pode sair com as colunas intercaladas
    linha a linha (ordem de leitura não garantida nesses casos).

    Retorna uma lista com o texto de OCR de cada página (mesma ordem/índice
    das páginas retornadas por extrair_por_pagina), usada tanto para gerar
    o arquivo de apoio quanto para a mesclagem automática no .md principal.
    """
    try:
        import fitz       # PyMuPDF
        import pytesseract
        from PIL import Image
        import io
    except ImportError as e:
        print(f'[OCR de página inteira] Dependência ausente ({e}). Instale com:')
        print('  pip install pymupdf pytesseract pillow --break-system-packages')
        print('  (+ pacote de idioma do Tesseract: apt-get install tesseract-ocr-por)')
        return []

    _configurar_tesseract()

    doc = fitz.open(caminho_pdf)
    paginas = []
    falhas = 0
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes('png')))
        try:
            texto = pytesseract.image_to_string(img, lang=cfg()['tesseract_lang'])
        except Exception as e:
            texto = f'[Falha no OCR desta página: {e}]'
            falhas += 1
        paginas.append(texto.strip())
    doc.close()

    if falhas > 0 and falhas == len(paginas):
        print(f'[ETAPA 3] AVISO: o OCR falhou em TODAS as {falhas} páginas — o Tesseract')
        print('[ETAPA 3] não foi encontrado/configurado corretamente. A mesclagem (Etapa 4)')
        print('[ETAPA 3] não vai funcionar até isso ser corrigido. Verifique a instalação')
        print('[ETAPA 3] do Tesseract e se o caminho do executável está correto.')
    elif falhas > 0:
        print(f'[ETAPA 3] AVISO: o OCR falhou em {falhas} de {len(paginas)} páginas.')

    return paginas


def extrair_por_pagina(caminho_pdf: str):
    """ETAPA 1 do fluxo: extrai o PDF para Markdown usando pymupdf4llm
    (layout-aware; cai em OCR automaticamente se a camada de texto do
    PDF estiver corrompida/com fonte quebrada). Retorna uma lista com o
    texto bruto de cada página, para permitir limpeza/mesclagem por página."""
    try:
        import pymupdf4llm
    except ImportError:
        print('Pacote não encontrado. Instale com:')
        print('  pip install pymupdf4llm --break-system-packages')
        sys.exit(1)

    print(f'[ETAPA 1] Extraindo {caminho_pdf} com pymupdf4llm ...')
    chunks = pymupdf4llm.to_markdown(caminho_pdf, page_chunks=True)
    paginas = [c['text'] for c in chunks]
    total_chars = sum(len(p) for p in paginas)
    print(f'[ETAPA 1] Extração bruta: {len(paginas)} páginas, {total_chars} caracteres')
    return paginas


def main():
    global IDIOMA_ATUAL

    if len(sys.argv) < 3:
        print('Uso: python3 pdf_to_clean_md.py entrada.pdf saida.md [--manter-backup] [--idioma pt|en|es]')
        print('  --manter-backup : também salva o arquivo .txt com OCR de página')
        print('                    inteira (por padrão, só o .md é gerado).')
        print('  --idioma pt|en|es : idioma do PDF de origem (padrão: pt).')
        sys.exit(1)

    caminho_pdf, caminho_md = sys.argv[1], sys.argv[2]
    extras = sys.argv[3:]
    manter_backup = '--manter-backup' in extras

    if '--idioma' in extras:
        idx = extras.index('--idioma')
        if idx + 1 >= len(extras) or extras[idx + 1] not in IDIOMAS:
            print(f"Idioma inválido. Use um de: {', '.join(IDIOMAS)}")
            sys.exit(1)
        IDIOMA_ATUAL = extras[idx + 1]

    print(f'[CONFIG] Idioma selecionado: {IDIOMA_ATUAL} (Tesseract: {cfg()["tesseract_lang"]})')

    # ETAPA 1 — extração (por página, para permitir mesclagem depois)
    paginas_brutas = extrair_por_pagina(caminho_pdf)

    # calcula o conjunto de linhas repetidas (cabeçalho/rodapé) no DOCUMENTO
    # INTEIRO antes de limpar página por página — a frequência só faz sentido
    # olhando para todas as páginas de uma vez
    todas_linhas = []
    for p in paginas_brutas:
        todas_linhas.extend(strip_picture_blocks(strip_extra_noise(p)).splitlines())
    repeated = detect_repeated_lines(todas_linhas)
    prefixos_repetidos = detectar_prefixos_repetidos(todas_linhas)
    sufixos_repetidos = detectar_sufixos_repetidos(todas_linhas)

    # ETAPA 2 — limpeza determinística, por página
    print('[ETAPA 2] Aplicando limpeza determinística (sem IA) ...')
    paginas_limpas = [limpar(p, repeated_override=repeated) for p in paginas_brutas]

    # ETAPA 3 — OCR de página inteira (rede de segurança, sempre roda — é
    # necessário para a mesclagem da Etapa 4, mesmo que o .txt não seja salvo)
    print('\n[ETAPA 3] Gerando OCR de página inteira (rede de segurança) ...')
    paginas_ocr = ocr_paginas_completas(caminho_pdf)

    if manter_backup and paginas_ocr:
        caminho_backup = caminho_md.rsplit('.', 1)[0] + '_backup_ocr_paginas.txt'
        backup_txt = '\n'.join(
            f'===== Página {i+1} =====\n{texto}\n' for i, texto in enumerate(paginas_ocr)
        )
        with open(caminho_backup, 'w', encoding='utf-8') as f:
            f.write(backup_txt)
        print(f'[ETAPA 3] Arquivo de apoio salvo em: {caminho_backup}')

    # ETAPA 4 — mesclagem automática: insere no .md o conteúdo de
    # figuras/quadros que o OCR de página inteira capturou de forma mais
    # completa do que o pymupdf4llm, marcando claramente para revisão
    print('[ETAPA 4] Mesclando conteúdo recuperado nas figuras/quadros incompletos ...')
    paginas_finais = []
    total_mesclagens = 0
    for i, pagina_md in enumerate(paginas_limpas):
        ocr_desta_pagina = paginas_ocr[i] if i < len(paginas_ocr) else ''
        mesclada = mesclar_pagina(pagina_md, ocr_desta_pagina)
        if mesclada != pagina_md:
            total_mesclagens += 1
        paginas_finais.append(mesclada)
    print(f'[ETAPA 4] {total_mesclagens} página(s) tiveram conteúdo complementado.')

    texto_final = '\n\n'.join(paginas_finais)
    texto_final = remover_cabecalhos_residuais_por_prefixo(texto_final, prefixos_repetidos)
    texto_final = remover_rodapes_por_sufixo(texto_final, sufixos_repetidos)
    texto_final = remover_cabecalhos_numerados_estruturais(texto_final)
    texto_final = remover_numeros_pagina_em_heading(texto_final)
    texto_final = collapse_blank_lines_str(texto_final)

    with open(caminho_md, 'w', encoding='utf-8') as f:
        f.write(texto_final)

    print(f'\nSalvo em: {caminho_md}')
    print(f'Resultado final: {len(texto_final)} caracteres, {len(texto_final.splitlines())} linhas')
    print('\nTrechos marcados com "⚠️ Conteúdo recuperado via OCR de página inteira"')
    print('foram inseridos automaticamente — revise-os contra o PDF original, pois a')
    print('ordem de colunas/caixas dentro da figura pode não ter sido preservada.')


def collapse_blank_lines_str(text: str) -> str:
    return '\n'.join(collapse_blank_lines(text.splitlines()))


if __name__ == '__main__':
    main()
