import { redirect } from 'next/navigation';

export default function MarketProfileRedirectPage() {
  redirect('/analytics?tab=profile');
}
