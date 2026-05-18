// shared/markdown.js — hardened markdown→HTML for community-authored content.
//
// Used by the in-app Plugin Store to render plugin authors' long_description.
// Authored content from the WP catalog flows through here before reaching the
// DOM, so this is the trust boundary for that content.
//
// Strategy: build up, don't tear down.
//   1) HTML-escape the entire source first — any literal <script>/<iframe>/
//      <img onerror>/etc lands as visible text, never as a real element.
//   2) Markdown rules selectively re-introduce a small allowlisted set of
//      tags via direct emission (never via passthrough).
//   3) Links pass through a scheme allowlist (https only). Markdown images
//      are stripped entirely — long_description should not embed images;
//      the catalog has a dedicated screenshot_url field.
//
// What's blocked:
//   - <script>, <iframe>, <object>, <embed>, <form>, on* event handlers — all
//     escape to text via step 1.
//   - javascript:, data:, file:, vbscript: links — rejected by scheme check
//     (case-insensitive).
//   - Markdown images — entirely removed.
//
// What's allowed:
//   - h1–h4, p, strong, em, code, pre, ul, ol, li, blockquote, hr, table,
//     thead, tbody, tr, th, td, br, a (https-only).
//
// Self-test: run `node interfaces/web/static/shared/markdown.js` from the
// project root to execute the nasty-input corpus and exit non-zero on any
// failure.

export function renderMarkdown(src) {
    if (!src) return '';
    // 1) Hard escape everything first — neutralizes raw HTML before any
    //    markdown rule runs. The build-up below explicitly re-emits the
    //    small set of tags we trust.
    let s = String(src)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

    // 2) Pull out fenced code blocks first so later rules don't mangle them.
    const codeBlocks = [];
    s = s.replace(/```(\w*)\n([\s\S]*?)```/g, (_, _lang, code) => {
        const id = `\x00CB${codeBlocks.length}\x00`;
        // code body is already HTML-escaped from step 1
        codeBlocks.push(`<pre class="md-code"><code>${code.trimEnd()}</code></pre>`);
        return id;
    });

    // 3) Inline code — also already escaped from step 1.
    s = s.replace(/`([^`\n]+)`/g, '<code class="md-inline-code">$1</code>');

    // 4) Markdown images — STRIPPED. Authored content is text + links + lists.
    //    Screenshots have their own catalog field.
    s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, '');

    // 5) Links — only emit <a> if href passes scheme allowlist.
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_full, text, href) => {
        return _isSafeHref(href)
            ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`
            : text;  // unsafe scheme → render plain text
    });

    // 6) Tables (must run before list/heading rules).
    s = s.replace(
        /^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)*)/gm,
        (_, hdr, _align, body) => {
            const cell = (raw, tag) =>
                raw.split('|').filter(c => c.trim()).map(c => `<${tag}>${c.trim()}</${tag}>`).join('');
            const rows = body.trim().split('\n').map(r => `<tr>${cell(r, 'td')}</tr>`).join('');
            return `<table class="md-table"><thead><tr>${cell(hdr, 'th')}</tr></thead><tbody>${rows}</tbody></table>`;
        }
    );

    // 7) Headings.
    s = s
        .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // 8) Horizontal rule.
    s = s.replace(/^---+$/gm, '<hr>');

    // 9) Bold + italic.
    s = s
        .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

    // 10) Lists — build <li> items, then group adjacent <li> lines under <ul>/<ol>.
    s = s.replace(/^(\s*)[-*] (.+)$/gm, '$1<li>$2</li>');
    s = s.replace(/^(\s*)\d+\. (.+)$/gm, '$1<li class="md-ol">$2</li>');
    // group consecutive <li> blocks (V1: simple ungrouped — wrap entire runs in ul)
    s = s.replace(/(?:<li(?: class="md-ol")?>[^]*?<\/li>(?:\n|$))+/g, (block) => {
        const isOrdered = block.includes('class="md-ol"');
        const cleaned = block.replace(/ class="md-ol"/g, '').trimEnd();
        return isOrdered ? `<ol>${cleaned}</ol>` : `<ul>${cleaned}</ul>`;
    });

    // 11) Blockquote.
    s = s.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

    // 12) Paragraphs — wrap orphan blocks of plain text. Skip lines that are
    //     already a block-level element or empty.
    s = s.split(/\n{2,}/).map(block => {
        const trimmed = block.trim();
        if (!trimmed) return '';
        if (/^<(h[1-4]|ul|ol|li|blockquote|pre|table|hr|p)\b/.test(trimmed)) return trimmed;
        return `<p>${trimmed.replace(/\n/g, '<br>')}</p>`;
    }).join('\n');

    // 13) Restore code blocks.
    s = s.replace(/\x00CB(\d+)\x00/g, (_, i) => codeBlocks[Number(i)]);

    return s;
}


function _isSafeHref(href) {
    if (typeof href !== 'string') return false;
    const trimmed = href.trim();
    // Disallow whitespace inside URL — common smuggling vector.
    if (/\s/.test(trimmed)) return false;
    // Strict allowlist: https only. (No bare http, no relative URLs, no
    // mailto/tel — long_description is plugin marketing text, https is what
    // makes sense.)
    return /^https:\/\//i.test(trimmed);
}


// ── Self-test corpus (runs when executed via Node) ──────────────────────────
// Each case asserts something specific about the output. Tests bias toward
// "must NOT contain" — better at catching escape-hatch regressions than
// "must contain" since markdown formatting can vary harmlessly.

const _CORPUS = [
    // Direct HTML injection — all neutralized by step 1.
    // Asserts no LIVE opening tag survives. The escaped text "<script>" → "&lt;script&gt;"
    // rendering as visible plain text is harmless, so we only forbid unescaped tags.
    { name: 'raw script tag',           in: '<script>alert(1)</script>',      mustNot: ['<script>', '<script ', '<script\n'] },
    { name: 'img onerror',              in: '<img src=x onerror=alert(1)>',   mustNot: ['<img'] },
    { name: 'iframe',                   in: '<iframe src="x"></iframe>',      mustNot: ['<iframe'] },
    { name: 'object/embed',             in: '<object data="x"><embed src="y">', mustNot: ['<object', '<embed'] },
    { name: 'form',                     in: '<form action="x"><input>',       mustNot: ['<form', '<input'] },
    { name: 'svg with onload',          in: '<svg onload="alert(1)">',        mustNot: ['<svg'] },

    // Link scheme attacks
    { name: 'javascript link',          in: '[click](javascript:alert(1))',   mustNot: ['javascript:', 'alert(1)'] },
    { name: 'mixed-case js link',       in: '[click](JaVaScRiPt:alert(1))',   mustNot: ['JaVaScRiPt:', 'alert(1)'] },
    { name: 'data html link',           in: '[click](data:text/html,<x>)',    mustNot: ['data:', '<x>'] },
    { name: 'file link',                in: '[click](file:///etc/passwd)',    mustNot: ['file:', 'passwd'] },
    { name: 'http (insecure) link',     in: '[click](http://example.com)',    mustNot: ['<a href="http:'] },
    { name: 'whitespace smuggle',       in: '[click](java script:alert(1))',  mustNot: ['java script:', 'alert(1)'] },

    // Image stripping
    { name: 'markdown image stripped',  in: '![alt](https://x.com/a.png)',    mustNot: ['<img', 'a.png', 'alt'] },
    { name: 'markdown image http',      in: '![](http://tracker/p.gif)',      mustNot: ['<img', 'tracker', 'p.gif'] },

    // Things that SHOULD work
    { name: 'safe https link',          in: '[click](https://example.com)',
      must: ['<a href="https://example.com"', 'target="_blank"', 'rel="noopener noreferrer"', '>click</a>'] },
    { name: 'heading',                  in: '# Hello',                        must: ['<h1>Hello</h1>'] },
    { name: 'bold',                     in: '**bold**',                       must: ['<strong>bold</strong>'] },
    { name: 'inline code',              in: '`code`',                         must: ['<code class="md-inline-code">code</code>'] },
    { name: 'list',                     in: '- a\n- b',                       must: ['<ul>', '<li>a</li>', '<li>b</li>', '</ul>'] },
];


function _runCorpus() {
    let failed = 0;
    for (const c of _CORPUS) {
        const out = renderMarkdown(c.in);
        const issues = [];
        for (const needle of (c.mustNot || [])) {
            if (out.includes(needle)) issues.push(`MUST_NOT contains "${needle}"`);
        }
        for (const needle of (c.must || [])) {
            if (!out.includes(needle)) issues.push(`MUST contain "${needle}"`);
        }
        if (issues.length === 0) {
            console.log(`  PASS  ${c.name}`);
        } else {
            failed++;
            console.log(`  FAIL  ${c.name}`);
            console.log(`        in:  ${JSON.stringify(c.in)}`);
            console.log(`        out: ${JSON.stringify(out)}`);
            for (const i of issues) console.log(`        - ${i}`);
        }
    }
    console.log(`\n${_CORPUS.length - failed}/${_CORPUS.length} passed`);
    return failed === 0;
}


// Node entry point — `node interfaces/web/static/shared/markdown.js`
if (typeof process !== 'undefined' && process.argv?.[1]?.endsWith('markdown.js')) {
    const ok = _runCorpus();
    process.exit(ok ? 0 : 1);
}
