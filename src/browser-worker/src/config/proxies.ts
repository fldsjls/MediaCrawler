import { ProxyConfiguration } from 'crawlee';

// Keep proxy URLs centralized so every crawler can opt into the same proxy pool.
const proxyUrls: string[] = [
    // 'http://user:password@host:port',
];

// Crawlee treats undefined as "run without proxy".
export function createProxyConfiguration(): ProxyConfiguration | undefined {
    if (proxyUrls.length === 0) return undefined;

    return new ProxyConfiguration({ proxyUrls });
}
