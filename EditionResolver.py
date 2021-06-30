from qgis.core import QgsProject
from qgis.core import Qgis, QgsField
from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsVectorLayer, QgsWkbTypes, QgsFeatureRequest, QgsVectorLayerEditBuffer, QgsFeature, QgsMapLayer
from shapely import wkt
import pprint
from . import dictionaries


def singleton(class_):
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]
    return getinstance


@singleton
class EditionResolver:
    """
    Tworzy kopię obiektów edytowanej warstwy
    w celu weryfikacji geometrii z aktualną
    geometrią w bazie danych
    """

    def __init__(self, iface):
        self.iface = iface
        self.layers = {}
        self.listeners = []
        self.activeLayer = None
        self._debug = False  # True | False
        # Prevent looped reloading of data
        self._isQgisOldVersion = self.checkifOldQgisVersion()

        self.checkQgisVersion()
        self.getLayers()
        self._onNewLayerAdded()
        self._onCurrentLayerChanged()
        self._onReadProject()
        # self._onLayerRemoved()

    def __del__(self):
        self.delete()

    def delete(self):
        for object, signal, callback in self.listeners:
            self.dprint(('delete', signal, callback))
            try:
                signal.disconnect(callback)
            except Exception as ex:
                self.dprint(('delete Exception signal.disconnect',
                             ex, object, signal, callback))
        try:
            del self.layers
        except Exception as ex:
            self.dprint(('delete Exception: Could not del self.layers', ex))

    def addListener(self, object, signal, callback):
        signal.connect(callback)
        self.listeners.append((object, signal, callback))

    def removeSingleListener(self, object, signal, callback):
        self.dprint(('removeSingleListener', signal))

        def tryToDisconnectSignal():
            try:
                signal.disconnect(callback)
            except Exception as ex:
                self.dprint((ex, object, signal, callback))

        def removeListenerFromStack():
            for _object, _signal, _callback in self.listeners:
                # self.dprint(
                #     ('removeListenerFromStack:', _signal, signal, _signal == signal, _callback, callback, _callback == callback, _object, object, _object == object))
                if (_object == object and _signal.__repr__() == signal.__repr__() and _callback == callback):
                    self.dprint(
                        ('Removing Listener:', _object, _signal, _callback))
                    self.listeners.remove((_object, _signal, _callback))
        tryToDisconnectSignal()
        removeListenerFromStack()

    # methods

    def getActiveLayer(self):
        return self.iface.activeLayer()

    def checkifOldQgisVersion(self):
        return Qgis.QGIS_VERSION_INT < 31400

    def checkQgisVersion(self):
        if (self._isQgisOldVersion):
            self.showWarningMessage(dictionaries.warning_old_qgis_version)

    def deleteTemporaryLayer(self, layer):
        self.dprint('deleteTemporaryLayer')
        del self.layers[layer]
        self.layers[layer] = None

    def deleteTemporaryLayerByLayerId(self, layerId):
        for layer in self.layers.keys():
            if (layer.id() == layerId):
                del self.layers[layer]
                self.layers[layer] = None

    def createTemporaryLayer(self, layer):
        # create temporary layer with old geometry
        crs = layer.sourceCrs().authid()
        name = layer.name() + '_old'
        geometryName = self.getLayerGeometryTypeName(layer)
        tempLayer = QgsVectorLayer(geometryName+"?crs="+crs, name, "memory")
        tempLayer_dataProvider = tempLayer.dataProvider()
        layer_clone = layer.clone()
        self.addFeaturesToLayer(tempLayer_dataProvider,
                                self.sortFeatureIterator(self.getLayerFeatures(layer)))
        tempLayer.updateExtents()
        # QgsProject.instance().addMapLayer(tempLayer)
        # tempLayer_nextFeature = next(tempLayer.getFeatures())
        # layer_nextFeature = next(layer.getFeatures())
        # self.dprint(('createTemporaryLayer first feature: ',
        #              'tempLayer',
        #              tempLayer_nextFeature.geometry(),
        #              tempLayer_nextFeature.id(),
        #              tempLayer.getFeature(1).geometry(
        #              ).boundingBox().asWktPolygon(),
        #              'layer',
        #              layer_nextFeature.geometry(),
        #              layer_nextFeature.id(),
        #              layer.getFeature(1).geometry(
        #              ).boundingBox().asWktPolygon()
        #              ))
        self.dprint(('createTemporaryLayer feature count: ',
                     tempLayer_dataProvider.featureCount(), tempLayer))
        self.showInfoMessage(
            dictionaries.temporary_control_layer_created(layer), dictionaries.edition_actived)
        return tempLayer

    def createBackupTemporaryLayer(self, layer):
        # create temporary layer with not commited geometry
        crs = layer.sourceCrs().authid()
        name = 'backup_' + layer.name()
        if (len(QgsProject.instance().mapLayersByName(name)) > 0):
            self.dprint(('createBackupTemporaryLayer layer exists', name))
            return QgsProject.instance().mapLayersByName(name)[0]
        geometryName = self.getLayerGeometryTypeName(layer)
        tempLayer = QgsVectorLayer(geometryName+"?crs="+crs, name, "memory")
        tempLayer_dataProvider = tempLayer.dataProvider()
        tempLayer_dataProvider.addAttributes([QgsField("id", QVariant.Int)])
        tempLayer.updateFields()
        QgsProject.instance().addMapLayer(tempLayer)
        return tempLayer

    def createTemporaryFeatureBackup(self, layer, featureId, editGeom, replaceFeature=False):
        backupLayer = self.createBackupTemporaryLayer(layer)
        backupLayer_features = self.getFeaturesByAttributeValue(
            self.getLayerFeatures(backupLayer), 'id', featureId)
        backupLayer_featureId = False
        if (len(backupLayer_features) > 0):
            backupLayer_featureId = backupLayer_features[0].id()

        if (backupLayer_featureId and self.getLayerFeature(backupLayer, backupLayer_featureId).hasGeometry()):
            if (replaceFeature):
                self.dprint(
                    ('createTemporaryFeatureBackup feature exists, replacing feature...'))
                self.changeLayerDataProviderFeatureGeometry(
                    backupLayer, backupLayer_featureId, editGeom)
            else:
                self.dprint(('createTemporaryFeatureBackup feature exists'))
        else:
            self.dprint(
                ('createTemporaryFeatureBackup feature does not exists, adding feature...'))
            backupFeature = self.createFeatureFromGeometry(editGeom, featureId)
            backupFeature.setFields(backupLayer.fields())
            backupFeature.setAttribute(0, featureId)
            self.addLayerFeatures(
                backupLayer, [backupFeature])
        backupLayer.updateExtents()

    def getLayers(self):
        self.activeLayer = self.getActiveLayer()
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if (self.isLayerValid(layer)):
                self.addLayerListeners(layer)
                self.layers[layer] = None
            elif (self.isVectorLayer(layer)):
                self.addLayerListenersForInvalidLayer(layer)

    def getLayersByName(self, name):
        return QgsProject.instance().mapLayersByName(name)

    def getLayerByName(self, name):
        try:
            return self.getLayersByName(name)[0]
        except:
            return None

    def isTypeOfMapLayer(self, object):
        if (isinstance(object, QgsMapLayer)):
            return True
        return False

    def showInvalidLayerMessages(self, layer):
        if (self.isFromDatabase(layer) and self.isSpatial(layer) and not self.isPolygon(layer)):
            self.showInfoMessage(dictionaries.info_layer_is_not_polygon)
        else:
            self.showInfoMessage(dictionaries.info_layer_is_not_valid)

    # Layer methods

    def addFeaturesToLayer(self, layer, features):
        for feature in features:
            layer.addFeatures([self.createFeatureFromGeometry(
                feature.geometry(), feature.id())])

    def getLayerFeatures(self, layer):
        return layer.dataProvider().getFeatures()

    def getLayerFeature(self, layer, featureId):
        provider = layer.dataProvider()
        if (provider.name() == 'memory'):
            return layer.getFeature(featureId)
        if (provider.name() == 'postgres'):
            freq = QgsFeatureRequest()
            freq.setFilterFid(featureId)
            freq_features = provider.getFeatures(freq)
            return list(freq_features)[0]
        return None

    def getLayerGeometryTypeName(self, layer):
        return QgsWkbTypes.geometryDisplayString(layer.geometryType())

    def changeLayerFeatureGeometry(self, layer, featureId, newGeometry):
        layer.changeGeometry(featureId, newGeometry)

    def updateLayerDataProvider(self, layer):
        layer.dataProvider().reloadData()

    def replaceTemporaryFeature(self, layer, featureId):
        # feature = QgsFeature(featureId)
        # feature.setGeometry(self.getLayerFeature(layer, featureId).geometry())
        self.layers[layer].dataProvider().changeGeometryValues(
            {featureId: self.getLayerFeature(layer, featureId).geometry()})
        self.layers[layer].updateExtents()

    def addLayerFeatures(self, layer, features):
        layer.dataProvider().addFeatures(features)

    def changeLayerDataProviderFeatureGeometry(self, layer, featureId, geometry):
        layer.dataProvider().changeGeometryValues(
            {featureId: geometry})
        layer.updateExtents()

    def rollbackEditionBuffer(self, layer, featureId, geometry):
        layer.editBuffer().changedGeometries().pop(featureId, None)
        layer.editBuffer().changeGeometry(featureId, geometry)
        self.dprint(('rollbackEditionBuffer',
                     layer.editBuffer().changedGeometries()))
        # layer.editBuffer().changedGeometries().changedGeometries()[featureId] = geometry

    # Feature methods

    def getFeaturesByAttributeValue(self, features, attribute, value):
        feats = []
        for feature in features:
            if (feature.attribute(attribute) == value):
                feats.append(feature)
        return feats

    def sortFeatureIterator(self, featuresIterator):
        features = {}
        for feature in featuresIterator:
            features[feature.id()] = feature
        self.dprint(('sortFeatureIterator: sorting features...'))
        return list(dict(sorted(features.items())).values())

    def createFeatureFromGeometry(self, geometry, featureId=None):
        if (featureId is not None):
            feature = QgsFeature(featureId)
        else:
            feature = QgsFeature()
        feature.setGeometry(geometry)
        return feature

    def getDifferences(self, oldFeature, newFeature):
        oldFeature_wkt = wkt.loads(oldFeature.geometry().asWkt())
        newFeature_wkt = wkt.loads(newFeature.geometry().asWkt())
        cut = (newFeature_wkt - oldFeature_wkt).wkt
        expand = (oldFeature_wkt - newFeature_wkt).wkt
        return (cut, expand)

    def rollbackFeatureEdition(self, layer, featureId, newGeom):
        self.replaceTemporaryFeature(layer, featureId)
        self.changeLayerDataProviderFeatureGeometry(layer, featureId, newGeom)
        self.updateLayerDataProvider(layer)
        self.updateLayerDataProvider(self.layers[layer])
        self.rollbackEditionBuffer(layer, featureId, newGeom)
        try:
            self.dprint(('rollbackFeatureEdition',
                         layer.editBuffer().changedGeometries()[featureId].asWkt()))
        except:
            self.dprint(('rollbackFeatureEdition',
                         layer.editBuffer().changedGeometries()))

        self.iface.mapCanvas().refresh()

    # Feature validations

    def compareGeometries(self, oldFeature, newFeature):
        return oldFeature.equals(newFeature)

    def checkEditedFeatures(self, layer, callback=None):
        self.dprint((layer, callback))
        if (self.layers[layer] is None):
            return
        for featureId in layer.editBuffer().changedGeometries():
            tempFeature_geometry = self.getLayerFeature(
                self.layers[layer], featureId).geometry()
            dbFeature_geometry = self.getLayerFeature(
                layer, featureId).geometry()
            editFeature_geometry = layer.editBuffer().changedGeometries()[
                featureId]
            if (self.compareGeometries(tempFeature_geometry, dbFeature_geometry)):
                self.dprint(('checkEditedFeatures: features equal'))
            else:
                self.dprint(('checkEditedFeatures: features not equal',
                             #  editFeature_geometry.asWkt(),
                             'tempFeature_geometry',
                             tempFeature_geometry.asWkt(),
                             'dbFeature_geometry',
                             dbFeature_geometry.asWkt()))
                if (callback is not None):
                    callback(layer, featureId, tempFeature_geometry,
                             dbFeature_geometry, editFeature_geometry)

    # layer listeners

    def addLayerListenersForInvalidLayer(self, layer):
        def _onEditingStarted():
            self.showInvalidLayerMessages(layer)
        self.addListener(layer, layer.editingStarted, _onEditingStarted)

    def addLayerListeners(self, layer):
        self.dprint(('addLayerListeners', layer))

        def _onRenderStarted():
            def _onProviderChanged(layer, featureId, oldGeom, newGeom, editGeom):
                message = dictionaries.featureChangedInDatabase(
                    layer, featureId)
                self.createTemporaryFeatureBackup(
                    layer, featureId, editGeom)
                self.showWarningMessage(
                    message)
                self.rollbackFeatureEdition(layer, featureId, newGeom)
            if (self._isQgisOldVersion):
                self.updateLayerDataProvider(layer)
            self.checkDataProvider(layer, _onProviderChanged)

        def _onRenderComplete():
            def compareTemporaryLayer():
                pass
                # temporaryFeatures = self.getLayerFeatures(self.layers[layer])
                # dbFeatures = self.getLayerFeatures(layer)
                # for feature in temporaryFeatures:
                #     dbFeature = self.getLayerFeature(layer, feature.id())
                #     if (not self.compareGeometries(feature.geometry(), dbFeature.geometry())):
                #         self.dprint(('compareTemporaryLayer', feature.id(), self.compareGeometries(
                #             feature.geometry(), dbFeature.geometry())))
                #     pass
                # pass
            self.dprint(('_onRenderComplete', layer,
                         self.activeLayer, self.activeLayer == layer))
            if (self.activeLayer == layer):
                compareTemporaryLayer()

        # def _onBeforeModifiedCheck():
        #     self.dprint('_onBeforeModifiedCheck')
        #     pass

        def _removeCanvasListeners():
            self.removeSingleListener(self.iface.mapCanvas(
            ), self.iface.mapCanvas().renderStarting, _onRenderStarted)
            self.removeSingleListener(self.iface.mapCanvas(
            ), self.iface.mapCanvas().renderComplete, _onRenderComplete)

        def _removeLayerEditionListeners():
            # self.removeSingleListener(
            #     layer, layer.beforeModifiedCheck, _onBeforeModifiedCheck)
            pass

        def _onEditingStarted():
            self.dprint(('_onEditingStarted'))
            self.updateLayerDataProvider(layer)
            self.layers[layer] = self.createTemporaryLayer(layer)
            self.addListener(self.iface.mapCanvas(
            ), self.iface.mapCanvas().renderStarting, _onRenderStarted)
            self.addListener(self.iface.mapCanvas(
            ), self.iface.mapCanvas().renderComplete, _onRenderComplete)
            # self.addListener(layer, layer.beforeModifiedCheck,
            #                  _onBeforeModifiedCheck)

        def _onEditingStopped():
            self.dprint(('_onEditingStopped'))
            self.deleteTemporaryLayer(layer)
            _removeCanvasListeners()
            _removeLayerEditionListeners()

        def _onBeforeCommitChanges():
            def _onProviderChanged(layer, featureId, oldGeom, newGeom, editGeom):
                self.dprint(
                    ('oldGeom', oldGeom.asWkt(), 'newGeom', newGeom.asWkt(), 'editGeom', editGeom.asWkt()))
                message = dictionaries.featureChangedInDatabase(
                    layer, featureId)
                self.createTemporaryFeatureBackup(
                    layer, featureId, editGeom, True)
                self.showWarningMessage(
                    message, dictionaries.warning_before_commit_changes)
                self.rollbackFeatureEdition(layer, featureId, newGeom)
            self.checkDataProvider(layer, _onProviderChanged)

        def _onAfterCommitChanges():
            def resetEdition():
                self.dprint('resetEdition')
                layer.rollBack(True)  # remove editions
                layer.startEditing()
            resetEdition()
            self.updateLayerDataProvider(layer)

        def _onWillBeDeleted():
            self.dprint(('Removing layer dependecies...'))
            self.removeSingleListener(
                layer, layer.willBeDeleted, _onWillBeDeleted)
            _removeCanvasListeners()
            self.removeLayerListenersByLayerId(layer.id())

        self.addListener(layer, layer.editingStarted, _onEditingStarted)
        self.addListener(layer, layer.editingStopped, _onEditingStopped)

        self.addListener(layer, layer.beforeCommitChanges,
                         _onBeforeCommitChanges)
        self.addListener(layer, layer.afterCommitChanges,
                         _onAfterCommitChanges)
        self.addListener(layer, layer.willBeDeleted, _onWillBeDeleted)

    def removeLayerListenersByLayerId(self, layerId):
        for object, signal, callback in self.listeners:
            try:
                self.dprint(('removeLayerListenersByLayerId', object, signal))
                if (self.isTypeOfMapLayer(object) and object.id() == layerId):
                    self.dprint((signal, object, 'disconnected'))
                    signal.disconnect(callback)
                    self.listeners.remove((object, signal, callback))
            except Exception as ex:
                self.dprint(('removeLayerListenersByLayerId', layerId, ex))

    def addTemporaryLayerListeners(self, tempLayer, layer):
        def _onWillBeDeleted():
            self.dprint(('Removing temporary layer...'))
            self.removeSingleListener(
                tempLayer, tempLayer.willBeDeleted, _onWillBeDeleted)
            layer.rollBack()

        self.addListener(tempLayer, tempLayer.willBeDeleted, _onWillBeDeleted)

    # Layer validations

    def checkDataProvider(self, layer, callback=None):
        self.checkEditedFeatures(layer, callback)

    def isLayerValid(self, layer):
        if (self.isFromDatabase(layer) and self.isVectorLayer(layer) and self.isSpatial(layer) and self.isPolygon(layer)):
            self.dprint(('isLayerValid: layer is valid', layer))
            return True
        self.dprint(('isLayerValid: layer is not valid', layer))
        return False

    def isSpatial(self, layer):
        return layer.isSpatial()

    def isFromDatabase(self, layer):
        return layer.dataProvider().name() == 'postgres'

    def isPolygon(self, layer):
        return self.getLayerGeometryTypeName(layer).lower() == 'polygon'

    def isVectorLayer(self, layer):
        return isinstance(layer, QgsVectorLayer)

    def isLayerEditionActive(self, layer):
        return isinstance(layer.editBuffer(), QgsVectorLayerEditBuffer)

    # qgis project/map listeners

    def _onNewLayerAdded(self):
        def _addLayer(layer):
            self.dprint('_onNewLayerAdded')
            if (self.isLayerValid(layer)):
                self.layers[layer] = None
                self.addLayerListeners(layer)

        self.addListener(QgsProject.instance(),
                         QgsProject.instance().layerWasAdded, _addLayer)

    def _onLayerRemoved(self):
        def _LayerRemoved(layerId):
            # self.removeLayerListenersByLayerId(layerId)
            pass
        self.addListener(QgsProject.instance(),
                         QgsProject.instance().layerRemoved, _LayerRemoved)

    def _onCurrentLayerChanged(self):
        def _currentLayerChanged(layer):
            self.dprint('_onCurrentLayerChanged')
            self.activeLayer = layer
            if (self.isVectorLayer(layer) and self.isLayerEditionActive(layer) and not self.isLayerValid(layer)):
                self.showInvalidLayerMessages(layer)
        self.addListener(self.iface.mapCanvas(), self.iface.mapCanvas(
        ).currentLayerChanged, _currentLayerChanged)

    def _onReadProject(self):
        def _readProject():
            self.dprint('_onReadProject')
            self.getLayers()
            self.showInfoMessage(dictionaries.project_loaded)

        self.addListener(QgsProject.instance(),
                         QgsProject.instance().readProject, _readProject)

    # User communication

    def showMessage(self, info, message, level, duration=10):
        self.iface.messageBar().pushMessage(
            info, message, level=level, duration=duration)

    def showErrorMessage(self, message, info=dictionaries.message_levels['ERROR']):
        self.showMessage(info, message, Qgis.Critical, duration=-1)

    def showWarningMessage(self, message, info=dictionaries.message_levels['WARNING']):
        self.showMessage(info, message, Qgis.Warning, duration=15)

    def showInfoMessage(self, message, info=dictionaries.message_levels['INFO']):
        self.showMessage(info, message, Qgis.Info, duration=10)

    def showSuccessMessage(self, message, info=dictionaries.message_levels['SUCCESS']):
        self.showMessage(info, message, Qgis.Success, duration=7)

    # debug message

    def dprint(self, message):
        if (self._debug == True):
            try:
                pprint.pprint(message)
            except:
                print(message)
