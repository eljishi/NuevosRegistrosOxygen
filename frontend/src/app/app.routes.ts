import { Routes } from '@angular/router';
import { ResumenComponent } from './pages/resumen/resumen.component';
import { UsuariosComponent } from './pages/usuarios/usuarios.component';
import { OfertasComponent } from './pages/ofertas/ofertas.component';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'resumen' },
  { path: 'resumen', component: ResumenComponent },
  { path: 'usuarios', component: UsuariosComponent },
  { path: 'ofertas', component: OfertasComponent },
  { path: '**', redirectTo: 'resumen' },
];
