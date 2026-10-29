import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from './server';

describe('Node fetch test transport cancellation', () => {
  it('accepts the same AbortSignal used by query functions', async () => {
    server.use(http.get('/api/v1/transport-probe', () => HttpResponse.json({ ok: true })));
    const response = await fetch('/api/v1/transport-probe', {
      signal: new AbortController().signal,
    });
    expect(await response.json()).toEqual({ ok: true });
  });

  it('still rejects an aborted request', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      fetch('/api/v1/transport-probe', { signal: controller.signal }),
    ).rejects.toMatchObject({
      name: 'AbortError',
    });
  });
});
