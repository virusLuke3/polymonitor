import { render } from 'preact';
import { App } from './App';
import { LocaleProvider } from '@/services/i18n';
import { registerPwa } from '@/services/pwa';
import { PanelResourceProvider } from '@/panels/usePanelResource';
import './styles/fonts.css';
import './styles/base-layer.css';
import './styles/panel-layout-stability.css';

registerPwa();
render(<LocaleProvider><PanelResourceProvider><App /></PanelResourceProvider></LocaleProvider>, document.getElementById('app')!);
