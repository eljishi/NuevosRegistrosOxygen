import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export type UserStatus = 'week' | 'month' | 'claimed' | 'expired';

export interface User {
  email: string;
  username: string;
  firstName: string;
  lastName: string;
  createdAt: string;
  lastVisit: string | null;
  firstSeenAt: string;
  offerExpiresAt: string;
  offerSentAt: string | null;
  offerClaimedAt: string | null;
  status: UserStatus;
}

export interface UsersResponse {
  users: User[];
  counts: Record<UserStatus, number>;
}

@Injectable({ providedIn: 'root' })
export class RegistrosService {
  private http = inject(HttpClient);
  private base = 'http://localhost:8000';

  list(status?: UserStatus): Observable<UsersResponse> {
    const q = status ? `?status=${status}` : '';
    return this.http.get<UsersResponse>(`${this.base}/api/users${q}`);
  }

  markClaimed(email: string): Observable<unknown> {
    return this.http.post(`${this.base}/api/users/${encodeURIComponent(email)}/claim`, {});
  }

  unmarkClaimed(email: string): Observable<unknown> {
    return this.http.delete(`${this.base}/api/users/${encodeURIComponent(email)}/claim`);
  }
}
