import './styles/app.css';
import { bootstrap } from './app/bootstrap';
import { fail } from './shared/dom';

bootstrap().catch(fail);
