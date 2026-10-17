import unittest
from internet_leads_monitor import relevant

class LaborDemandTests(unittest.TestCase):
    def test_observed_foreman_card_rejected(self):
        self.assertFalse(relevant('Нужен прораб', 'Ищем бригадира. Бригада и бытовка на месте. Монолитная подпорная стена, дренаж, траншеи. Контроль земляных работ и фотоотчет.'))
    def test_crew_leader_inflection_rejected(self):
        self.assertFalse(relevant('Ищем бригадиров', 'Контроль стройплощадки, земляные работы, демонтаж конструкций.'))
    def test_foreman_contact_does_not_block_explicit_truck_demand(self):
        self.assertTrue(relevant('Нужен самосвал', 'Вывоз грунта, 100 м3, контакт прораба.'))
    def test_mixed_vacancy_and_real_equipment_demand_allowed(self):
        self.assertTrue(relevant('Нужен прораб и нужен экскаватор', 'Земляные работы на объекте.'))
    def test_plain_earthwork_demand_preserved(self):
        self.assertTrue(relevant('Земляные работы', 'Разработка котлована, нужен экскаватор, вывоз грунта.'))

if __name__ == '__main__':
    unittest.main()
