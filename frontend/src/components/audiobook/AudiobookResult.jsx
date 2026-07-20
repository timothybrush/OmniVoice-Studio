import React from 'react';
import { Download } from 'lucide-react';
import { audioUrl } from '../../api/generate';
import { buttonVariants } from '@/components/ui/button.tsx';

/**
 * The finished-render result: the "ready" note (with cached/failed chapter
 * summaries), the player, and the Download link. Extracted from AudiobookTab to
 * keep that page under the line lint; behaviour is unchanged.
 */
export default function AudiobookResult({ t, output, done }) {
  return (
    <div className="audiobook-done">
      <div style={{ marginBottom: 8 }}>✅ {t('audiobook.ready')}</div>
      {done && done.failed_chapters.length > 0 && (
        <div className="muted" style={{ marginBottom: 8 }}>
          {t('audiobook.failed_note', { count: done.failed_chapters.length })}
        </div>
      )}
      {done && done.cached_chapters > 0 && (
        <div className="muted" style={{ marginBottom: 8 }}>
          {t('audiobook.cached_note', { count: done.cached_chapters })}
        </div>
      )}
      <audio controls src={audioUrl(output)} style={{ width: '100%' }} />
      <div style={{ marginTop: 8 }}>
        <a
          className={buttonVariants({ variant: 'subtle', size: 'omniMd' })}
          href={audioUrl(output)}
          download={output}
        >
          <Download size={14} /> {t('audiobook.download')}
        </a>
      </div>
    </div>
  );
}
