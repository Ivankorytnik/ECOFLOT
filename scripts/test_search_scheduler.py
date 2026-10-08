import unittest
from datetime import datetime
from scheduled_cycle_runner import MSK, scheduled_slot, refreshed_state


class SchedulerContracts(unittest.TestCase):
    def test_delayed_morning_stays_morning(self):
        self.assertEqual(scheduled_slot('7,17,27 5 * * *', datetime(2026, 10, 7, 15, 2, tzinfo=MSK)), '2026-10-07 08:00')

    def test_delayed_afternoon_stays_afternoon(self):
        self.assertEqual(scheduled_slot('7,17,27 11 * * *', datetime(2026, 10, 7, 19, 2, tzinfo=MSK)), '2026-10-07 14:00')

    def test_delayed_evening_crosses_midnight(self):
        self.assertEqual(scheduled_slot('7,17,27 15 * * *', datetime(2026, 10, 8, 0, 2, tzinfo=MSK)), '2026-10-07 18:00')

    def test_all_backup_minutes_share_key(self):
        keys = {scheduled_slot('7,17,27 5 * * *', datetime(2026, 10, 7, 8, minute, tzinfo=MSK)) for minute in (7, 17, 27, 59)}
        self.assertEqual(keys, {'2026-10-07 08:00'})

    def test_legacy_expression_still_maps_after_deployment(self):
        self.assertEqual(scheduled_slot('0,12,32 5 * * *', datetime(2026, 10, 8, 12, 0, tzinfo=MSK)), '2026-10-08 08:00')

    def test_ambiguous_combined_schedule_rejected(self):
        with self.assertRaises(ValueError):
            scheduled_slot('7,17,27 5,11,15 * * *')

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            scheduled_slot('7,17,27 5 * * *', datetime(2026, 10, 7, 8))

    @staticmethod
    def audit(rows, expected, ids=None):
        found = {row[0] for row in rows}
        ids = found if ids is None else set(ids)
        confirmed = len(found & ids) if expected else 0
        pending = len(ids) - confirmed
        return {'checked': len(found & ids), 'confirmed': confirmed, 'pending': pending,
                'missing_records': len(ids-found), 'ok': bool(expected) and not pending}

    def state(self, status='DELIVERY_PENDING', accepted=1):
        return {'cycleKey': '2026-10-07 08:00', 'run_id': 'r.1', 'status': status, 'totals': {'accepted': accepted}}

    def test_late_receipt_finishes_delivery(self):
        prior = self.state()
        result = refreshed_state(prior, [['A']], {'1'}, {'A': {'run_id': 'r.1'}}, self.audit)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(prior['status'], 'DELIVERY_PENDING')

    def test_late_receipt_cannot_repair_source_failure(self):
        for status in ('SEARCH_PARTIAL', 'SEARCH_FAILED'):
            result = refreshed_state(self.state(status), [['A']], {'1'}, {'A': {'run_id': 'r.1'}}, self.audit)
            self.assertEqual(result['status'], status)

    def test_missing_ledger_cannot_produce_success(self):
        result = refreshed_state(self.state('COMPLETE'), [], {'1'}, {}, self.audit)
        self.assertFalse(result['delivery']['ok'])
        self.assertEqual(result['delivery']['missing_receipts'], 1)
        self.assertEqual(result['status'], 'DELIVERY_PENDING')

    def test_duplicate_without_identity_stays_unverified(self):
        result = refreshed_state(self.state(), [], {'1'}, {'A': {'run_id': 'r.1', 'duplicate': True}}, self.audit)
        self.assertEqual(result['delivery']['unresolved_duplicate_references'], 1)
        self.assertEqual(result['delivery']['pending_new_or_known_records'], 0)
        self.assertFalse(result['delivery']['ok'])

    def test_old_run_receipt_cannot_produce_success(self):
        result = refreshed_state(self.state(), [['A']], {'1'}, {'A': {'run_id': 'older.1'}}, self.audit)
        self.assertFalse(result['delivery']['ok'])


if __name__ == '__main__':
    unittest.main()
