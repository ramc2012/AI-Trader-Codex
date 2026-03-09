import { redirect } from 'next/navigation';

export default function MoneyFlowRedirectPage() {
  redirect('/analytics?tab=moneyflow');
}
