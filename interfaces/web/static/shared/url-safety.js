// shared/url-safety.js — URL scheme allowlist for community-authored content.
//
// Plugin metadata fields like author_url, github_url, screenshot_url come
// from sapphireblue.dev's catalog — anyone can submit a plugin, so we treat
// them as untrusted strings. This module is the single place that decides
// whether a URL is safe to render into href/src.
//
// Strict allowlist: https only. No bare http, no mailto/tel, no
// javascript:/data:/file: smuggling. Whitespace inside URL is rejected
// (common bypass via newlines or tabs). Used by:
//   - shared/markdown.js (existing — for plugin long-description anchors)
//   - views/store.js (cards: author_url, github_url, screenshot_url)
//   - views/settings-tabs/dashboard.js (Plugin Spotlight tile author_url)
//
// If you need a different scheme later, add it here, not at the call site.


export function isSafeHref(href) {
    if (typeof href !== 'string') return false;
    const trimmed = href.trim();
    if (/\s/.test(trimmed)) return false;
    return /^https:\/\//i.test(trimmed);
}


/**
 * Sanitize a URL for use in href/src attributes. Returns the URL if safe,
 * empty string otherwise. Use when you want a falsy fallback you can
 * conditional-render around.
 */
export function safeUrl(href) {
    return isSafeHref(href) ? href : '';
}


// ── Self-test corpus (runs when executed via Node) ──────────────────────────
// Pinning behavior of the URL gate against community-content attack vectors.
// Tests bias toward "must reject" — the surface this guards is community-
// authored plugin metadata (author_url, github_url, screenshot_url) that
// gets rendered into href/src attributes.

const _CORPUS = [
    // Must REJECT — known attack schemes
    { name: 'javascript: scheme',           in: 'javascript:alert(1)',                       expect: false },
    { name: 'JaVaScRiPt mixed case',        in: 'JaVaScRiPt:alert(1)',                       expect: false },
    { name: 'JAVASCRIPT all upper',         in: 'JAVASCRIPT:alert(1)',                       expect: false },
    { name: 'leading whitespace',           in: '  javascript:alert(1)',                     expect: false },
    { name: 'space inside URL',             in: 'java script:alert(1)',                      expect: false },
    { name: 'newline inside URL',           in: 'java\nscript:alert(1)',                     expect: false },
    { name: 'tab inside URL',               in: 'java\tscript:alert(1)',                     expect: false },
    { name: 'data:text/html',               in: 'data:text/html,<script>alert(1)</script>',  expect: false },
    { name: 'data:image/svg+xml',           in: 'data:image/svg+xml,<svg onload=alert(1)>',  expect: false },
    { name: 'file:///',                     in: 'file:///etc/passwd',                        expect: false },
    { name: 'vbscript:',                    in: 'vbscript:msgbox(1)',                        expect: false },

    // Must REJECT — non-https schemes / non-absolute
    { name: 'plain http (insecure)',        in: 'http://example.com',                        expect: false },
    { name: 'mailto:',                      in: 'mailto:test@example.com',                   expect: false },
    { name: 'tel:',                         in: 'tel:+1234567890',                           expect: false },
    { name: 'protocol-relative //',         in: '//evil.com/foo',                            expect: false },
    { name: 'absolute path /',              in: '/local/path',                               expect: false },
    { name: 'relative path',                in: 'path/to/foo',                               expect: false },
    { name: 'hash-only fragment',           in: '#section',                                  expect: false },
    { name: 'just a domain',                in: 'example.com',                               expect: false },

    // Must REJECT — non-strings and degenerate inputs
    { name: 'empty string',                 in: '',                                          expect: false },
    { name: 'whitespace only',              in: '   ',                                       expect: false },
    { name: 'null',                         in: null,                                        expect: false },
    { name: 'undefined',                    in: undefined,                                   expect: false },
    { name: 'number',                       in: 123,                                         expect: false },
    { name: 'object',                       in: {},                                          expect: false },
    { name: 'array',                        in: ['https://x.com'],                           expect: false },

    // Must ACCEPT — valid https URLs
    { name: 'plain https',                  in: 'https://example.com',                       expect: true  },
    { name: 'https with path + query',      in: 'https://example.com/foo?bar=1',             expect: true  },
    { name: 'https github',                 in: 'https://github.com/user/repo',              expect: true  },
    { name: 'HTTPS uppercase scheme',       in: 'HTTPS://example.com',                       expect: true  },
    { name: 'https with port',              in: 'https://example.com:8443/path',             expect: true  },
    { name: 'https with fragment',          in: 'https://example.com/page#section',          expect: true  },
];


function _runCorpus() {
    let failed = 0;
    for (const c of _CORPUS) {
        const got = isSafeHref(c.in);
        if (got === c.expect) {
            console.log(`  PASS  ${c.name}`);
        } else {
            failed++;
            console.log(`  FAIL  ${c.name}`);
            console.log(`        in:       ${JSON.stringify(c.in)}`);
            console.log(`        got:      ${got}`);
            console.log(`        expected: ${c.expect}`);
        }
    }
    console.log(`\n${_CORPUS.length - failed}/${_CORPUS.length} passed`);
    return failed === 0;
}


// Node entry point — `node interfaces/web/static/shared/url-safety.js`
if (typeof process !== 'undefined' && process.argv?.[1]?.endsWith('url-safety.js')) {
    const ok = _runCorpus();
    process.exit(ok ? 0 : 1);
}
