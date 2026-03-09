import { redirect } from 'next/navigation';

export default function OrderFlowRedirectPage() {
  redirect('/analytics?tab=orderflow');
}
