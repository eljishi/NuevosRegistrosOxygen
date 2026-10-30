import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RegistrosService, User } from '../../registros.service';

@Component({
  selector: 'app-ofertas',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './ofertas.component.html',
  styleUrl: './ofertas.component.scss',
})
export class OfertasComponent implements OnInit {
  private api = inject(RegistrosService);

  users = signal<User[]>([]);
  loading = signal(false);
  error = signal<string | null>(null);

  ngOnInit() { this.load(); }

  load() {
    this.loading.set(true);
    this.error.set(null);
    this.api.list('claimed').subscribe({
      next: (r) => { this.users.set(r.users); this.loading.set(false); },
      error: (e) => { this.error.set(e?.message ?? 'Error'); this.loading.set(false); },
    });
  }

  fmt(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  daysToReturn(u: User): string {
    if (!u.offerClaimedAt || !u.firstSeenAt) return '—';
    const diff = new Date(u.offerClaimedAt).getTime() - new Date(u.firstSeenAt).getTime();
    const days = Math.floor(diff / 86400000);
    return `${days}d`;
  }
}
