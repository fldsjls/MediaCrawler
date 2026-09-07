// Normalize visible row text before collect stages decide whether it is usable.
function cleanText(text: string): string {
    return text.trim().replace(/\s+/g, ' ');
}

// Durations are stripped from row text before the lesson title is validated.
const DURATION_RE = /\b\d{1,2}:\d{2}(?::\d{2})?\b/;
const LESSON_TITLE_RE = /(?:\u7b2c[\d\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e07\u4e24]+\s*[\u7ae0\u8282\u8bfe\u8bb2])|(?:[\d\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+\s*[.\u3001-]\s*\S+)/u;

// Navigation labels can share the same sidebar area but are not lesson rows.
const NAVIGATION_LABELS = new Set([
    '\u9996\u9875',
    '\u5b66\u4e60\u4e2d\u5fc3',
    '\u8bfe\u7a0b\u4e2d\u5fc3',
    '\u4e2a\u4eba\u4e2d\u5fc3',
    '\u6211\u7684\u8bfe\u7a0b',
]);

function looksLikeLessonTitle(text: string): boolean {
    if (NAVIGATION_LABELS.has(text)) return false;
    return LESSON_TITLE_RE.test(text);
}

export function parseLessonText(rawText: string): { title: string; duration?: string } | undefined {
    const raw = cleanText(rawText);
    if (!raw) return undefined;

    const duration = raw.match(DURATION_RE)?.[0];
    const title = cleanText(duration ? raw.replace(duration, '') : raw);
    if (!looksLikeLessonTitle(title)) return undefined;

    return { title, duration };
}
