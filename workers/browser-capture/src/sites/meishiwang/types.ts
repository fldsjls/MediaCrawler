// Lesson metadata collected before clicking each Meishiwang row.
export interface MeishiwangLesson {
    index: number;
    title: string;
    duration?: string;
    chapter?: string;
}

// Site-specific export record consumed by the downloader and review workflows.
export interface MeishiwangM3u8Item {
    site: 'meishiwang';
    courseUrl: string;
    pageUrl: string;
    courseTitle?: string;
    lessonIndex: number;
    lessonTitle: string;
    duration?: string;
    chapter?: string;
    url: string;
    m3u8Url: string;
    cdnHost?: string;
    sourceUrl?: string;
    foundAt: string;
}

export interface MeishiwangRawM3u8Item extends MeishiwangM3u8Item {
    rawIndex: number;
    captureSource: 'page-scan' | 'request';
}
