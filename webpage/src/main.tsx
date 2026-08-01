import { render } from 'preact';
import { App } from './App';
import { LocaleProvider } from '@/services/i18n';
import { registerPwa } from '@/services/pwa';
import '@fontsource-variable/jetbrains-mono/wght.css';
import '@fontsource-variable/space-grotesk/wght.css';
import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/base-layer.css';
import './styles/panel-layout-stability.css';

registerPwa();
render(<LocaleProvider><App /></LocaleProvider>, document.getElementById('app')!);
