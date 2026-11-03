import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { BrevoState, ChainResponse, ChainUser, RegistrosService } from '../../registros.service';

@Component({
  selector: 'app-usuarios',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './usuarios.component.html',
  styleUrl: './usuarios.component.scss',
})
export class UsuariosComponent implements OnInit {
  private api = inject(RegistrosService);

  users = signal<ChainUser[]>([]);
  counts = signal<Record<BrevoState, number>>({ pending: 0, sent: 0 });
  filter = signal<BrevoState | null>(null);
  search = signal('');
  loading = signal(false);
  error = signal<string | null>(null);

  visibleUsers = computed(() => {
    const q = this.search().trim().toLowerCase();
    if (!q) return this.users();
    return this.users().filter(u =>
      (u.username || '').toLowerCase().includes(q) ||
      (u.email || '').toLowerCase().includes(q) ||
      (u.firstName || '').toLowerCase().includes(q) ||
      (u.lastName || '').toLowerCase().includes(q)
    );
  });

  ngOnInit() { this.load(); }

  load() {
    this.loading.set(true);
    this.error.set(null);
    this.api.chain(this.filter() ?? undefined).subscribe({
      next: (r: ChainResponse) => {
        this.users.set(r.users);
        this.counts.set(r.counts);
        this.loading.set(false);
      },
      error: (e) => {
        this.error.set(e?.message ?? 'Error cargando usuarios');
        this.loading.set(false);
      },
    });
  }

  setFilter(f: BrevoState | null) { this.filter.set(f); this.load(); }

  toggleClaim(u: ChainUser) {
    const op = u.offerClaimedAt ? this.api.unmarkClaimed(u.email) : this.api.markClaimed(u.email);
    op.subscribe({ next: () => this.load() });
  }

  fmt(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleString('es-ES', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  totalCount(): number {
    const c = this.counts();
    return c.pending + c.sent;
  }
}
