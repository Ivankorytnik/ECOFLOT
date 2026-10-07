import unittest
from search_recipients import active_chats


class RecipientTests(unittest.TestCase):
    def test_null_id_cannot_shrink_audience(self):
        with self.assertRaisesRegex(ValueError, 'APPROVED_RECIPIENT_ID'):
            active_chats([['', 'approved'], ['33', 'approved']])

    def test_none_id_cannot_shrink_audience(self):
        with self.assertRaisesRegex(ValueError, 'APPROVED_RECIPIENT_ID'):
            active_chats([[None, 'approved']])

    def test_three_recipients_not_one(self):
        self.assertEqual(active_chats([['11','approved'],['22','approved'],['44','blocked'],['33','approved']]), {'11','22','33'})

    def test_blocked_wins_over_duplicate_approval(self):
        self.assertEqual(active_chats([['11','approved'],['11','blocked']]), set())

    def test_blank_tail_ignored(self):
        self.assertEqual(active_chats([[], ['', ''], [None, None], ['11','approved']]), {'11'})

    def test_combined_ids_rejected(self):
        with self.assertRaises(ValueError):
            active_chats([['11,22','approved']])

    def test_missing_role_is_not_approved(self):
        self.assertEqual(active_chats([['11','']]), set())

    def test_missing_column_stops_preflight(self):
        with self.assertRaises(ValueError):
            active_chats([['11']])


if __name__ == '__main__':
    unittest.main()
