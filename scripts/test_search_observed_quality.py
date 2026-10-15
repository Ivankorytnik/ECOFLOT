import unittest
from internet_leads_monitor import relevant, infer_work_equipment, CONTACT_GATED_ALLOWED_DOMAINS

class ObservedQualityTests(unittest.TestCase):
    def test_land_clearing_is_not_tko_collection(self):
        work, equipment = infer_work_equipment('Расчистка участка', 'Площадь 670 м2. Убрать 2 березы, кусты, снять слой почвы с растительностью. Сделать по аналогии с очищенным участком.')
        self.assertIn('Расчистка', work)
        self.assertNotIn('Мусоровоз', equipment)

    def test_tko_must_be_a_whole_word(self):
        for word in ('участком', 'участков', 'участковые'):
            work, equipment = infer_work_equipment('Работа с ' + word, '')
            self.assertNotIn('ТКО', work)
            self.assertNotIn('Мусоровоз', equipment)

    def test_real_tko_still_allowed(self):
        work, equipment = infer_work_equipment('Вывоз ТКО', 'Нужен регулярный вывоз ТКО')
        self.assertIn('ТКО', work)
        self.assertEqual(equipment, 'Мусоровоз')

    def test_real_waste_truck_still_allowed(self):
        work, equipment = infer_work_equipment('Нужен мусоровоз', 'Вывоз мусора')
        self.assertEqual(equipment, 'Мусоровоз')

    def test_facade_workers_and_provided_truck_are_not_transport_demand(self):
        self.assertFalse(relevant('Требуются монтажники вентилируемых фасадов', 'Предоставим агрегаты, фасадные подъемники, материалы, технику, мусоровоз. Московская область, Пушкино.'))

    def test_inflected_labor_count_rejected(self):
        self.assertFalse(relevant('Земляные работы', 'Количество разнорабочих: 1 человек. Пересадить пять кустов.'))

    def test_explicit_truck_demand_kept(self):
        self.assertTrue(relevant('Нужны разнорабочие и самосвал', 'Требуется самосвал для вывоза грунта.'))

    def test_pure_soil_haul_kept(self):
        self.assertTrue(relevant('Нужен самосвал', 'Вывоз грунта с участка, Москва.'))

    def test_soil_layer_removal_is_clearing(self):
        work, equipment = infer_work_equipment('Работы на участке', 'Снять слой почвы с растительностью')
        self.assertIn('Расчистка', work)

    def test_approved_contact_exceptions_kept(self):
        self.assertIn('profi.ru', CONTACT_GATED_ALLOWED_DOMAINS)
        self.assertIn('vezetvsem.ru', CONTACT_GATED_ALLOWED_DOMAINS)

if __name__ == '__main__':
    unittest.main()
