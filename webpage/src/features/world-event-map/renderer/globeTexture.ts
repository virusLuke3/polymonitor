import { MAP_RENDERER_TIMEOUTS } from './MapRenderer';

/** One cancellable 3D asset, started alongside the lazy engine download. */
export class GlobeTexture {
  private disposed = false;
  private claimed = false;
  private pending: Promise<string> | null = null;
  private textureRequest: AbortController | null = null;
  private textureUrl: string | null = null;
  load() { return this.pending ||= this.download(); }
  claim() {
    if (this.claimed || this.disposed) return new GlobeTexture();
    this.claimed = true;
    return this;
  }
  disposeUnclaimed() { if (!this.claimed) this.dispose(); }
  dispose() {
    this.disposed = true;
    this.textureRequest?.abort();
    if (this.textureUrl) URL.revokeObjectURL(this.textureUrl);
    this.textureUrl = null;
  }
  private async download(): Promise<string> {
    // globe.gl's image loader has no error callback and can otherwise leave
    // onGlobeReady pending until the generic renderer deadline. Own this one
    // asset's bounded request so switching views also cancels its download.
    for (let attempt = 0; attempt < 2; attempt++) {
      const controller = new AbortController();
      this.textureRequest = controller;
      const deadline = setTimeout(() => controller.abort(), MAP_RENDERER_TIMEOUTS.primary);
      let url: string | null = null;
      try {
        const response = await fetch('/textures/earth-topo-bathy.jpg', {
          signal: controller.signal, cache: attempt ? 'reload' : 'default',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        url = URL.createObjectURL(await response.blob());
        const image = new Image();
        image.src = url;
        const cancelDecode = () => { image.src = ''; };
        controller.signal.addEventListener('abort', cancelDecode, { once: true });
        try { await image.decode(); }
        finally { controller.signal.removeEventListener('abort', cancelDecode); }
        if (this.disposed || controller.signal.aborted) throw new Error('Texture loading cancelled or timed out.');
        this.textureUrl = url;
        return url;
      } catch (error) {
        if (url) URL.revokeObjectURL(url);
        if (this.disposed || attempt === 1) throw new Error(
          `3D Earth texture could not load: ${error instanceof Error ? error.message : String(error)}`,
        );
      } finally {
        clearTimeout(deadline);
        if (this.textureRequest === controller) this.textureRequest = null;
      }
    }
    throw new Error('3D Earth texture could not load.');
  }

}
