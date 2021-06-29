message_levels = {
    'INFO': 'Informacja',
    'ERROR': 'Błąd',
    'WARNING': 'Uwaga',
    'SUCCESS': 'Sukces'
}

disable_editions = 'Zakończ edycję warstw.'
edition_actived = 'Aktywowano edycję.'
project_loaded = 'Załadowano projekt.'
warning_before_commit_changes = 'Błąd podczas zapisywania zmian.'
warning_old_qgis_version = 'Korzystasz z wersji QGISa starszej niż 3.16.0, niektóre funkcje mogą działać nieprawidłowo.'
info_layer_is_not_polygon = 'Warstwa nie jest typu poligonowego! Wersja obiektów nie będzie kontrolowana.'
info_layer_is_not_valid = 'Warstwa nie obsługuje kontroli wersji obiektów.'


def featureChangedInDatabase(layer, featureId):
    # message = 'Feature with an ID: {} of layer: {} has been changed in the database since editing started. Rollbacking changes.'.format(featureId, layer.name())
    message = 'Obiekt o ID: {} w warstwie: {} został zmieniony w bazie danych od czasu rozpoczęcia edycji. Wycofywanie zmian...'.format(
        featureId, layer.name())
    return message


def temporary_control_layer_created(layer):
    message = 'Utworzono warstwę kontroli wersji obiektów dla warstwy: {}'.format(
        layer.name())
    return message
