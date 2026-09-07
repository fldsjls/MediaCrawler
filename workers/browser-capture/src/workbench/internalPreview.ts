// Shared reserved-path protocol with api/workbench/preview/internal.py.
export function isInternalPreviewUrl(value: string): boolean {
    try {
        const url = new URL(value);
        return ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
            && url.pathname.startsWith('/__mediacrawler_preview__/');
    } catch { return false; }
}
