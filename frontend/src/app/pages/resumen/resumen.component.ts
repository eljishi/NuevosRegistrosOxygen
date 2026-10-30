import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RegistrosService, UserStatus } from '../../registros.service';

@Component({
  selector: 'app-resumen',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './resumen.component.html',
  styleUrl: './resumen.component.scss',
})
export class ResumenComponent implements OnInit {
  private api = inject(RegistrosService);

  counts = signal<Record<UserStatus, number>>({ week: 0, month: 0, claimed: 0, expired: 0 });
  loading = signal(false);
  error = signal<string | null>(null);

  ngOnInit() {
    this.loading.set(true);
    this.api.list().subscribe({
      next: (r) => { this.counts.set(r.counts); this.loading.set(false); },
      error: (e) => { this.error.set(e?.message ?? 'Error'); this.loading.set(false); },
    });
  }

  total(): number {
    const c = this.counts();
    return c.week + c.month + c.claimed;
  }
}
