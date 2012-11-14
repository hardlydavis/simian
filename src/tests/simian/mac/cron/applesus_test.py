#!/usr/bin/env python
# 
# Copyright 2010 Google Inc. All Rights Reserved.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# #

"""applesus module tests."""



import datetime
import logging
logging.basicConfig(filename='/dev/null')
import urlparse

from google.apputils import app
from tests.simian.mac.common import test
import mox
import stubout
from simian.mac.cron import applesus


class AppleSusModuleTest(mox.MoxTestBase):
  def testCatalogsDictionary(self):
    """Test global CATALOGS value."""
    self.assertTrue(hasattr(applesus, 'CATALOGS'))
    self.assertTrue(type(applesus.CATALOGS) is type({}))

    for k in applesus.CATALOGS:
      # Key should be e.g. "10.6"
      self.assertTrue(k.startswith('10.'), 'CATALOGS key strange')
      p = urlparse.urlparse(applesus.CATALOGS[k])
      self.assertEqual(len(p), 6)
      self.assertEqual(p[0], 'https')
      self.assertTrue(p[1].endswith('.apple.com'))


class AppleSUSCatalogSyncTest(test.RequestHandlerTest):

  def GetTestClassInstance(self):
    return applesus.AppleSUSCatalogSync()

  def GetTestClassModule(self):
    return applesus

  def testUpdateCatalogIfChanged(self):
    """Test _UpdateCatalogIfChanged()."""
    self.mox.StubOutWithMock(applesus.urlfetch, 'fetch')
    self.mox.StubOutWithMock(self.c, '_UpdateCatalog')

    deadline = 30
    xml = 'this is xml'
    catalog = self.mox.CreateMockAnything()
    catalog.last_modified_header = 'lmh'
    headers = {'If-Modified-Since': catalog.last_modified_header}
    response = self.mox.CreateMockAnything()
    response.status_code = 200
    response.content = xml
    response.headers = {'Last-Modified': 'hds'}

    url = applesus.CATALOGS.values()[0]

    applesus.urlfetch.fetch(
        url, headers=headers, deadline=deadline,
        validate_certificate=True).AndReturn(response)
    self.c._UpdateCatalog(xml, entity=catalog, last_modified='hds')

    self.mox.ReplayAll()
    self.assertTrue(self.c._UpdateCatalogIfChanged(catalog, url))
    self.mox.VerifyAll()

  def testUpdateCatalogIfChangedWhen304(self):
    """Test _UpdateCatalogIfChanged()."""
    self.mox.StubOutWithMock(applesus.urlfetch, 'fetch')
    self.mox.StubOutWithMock(self.c, '_UpdateCatalog')

    deadline = 30
    catalog = self.mox.CreateMockAnything()
    catalog.last_modified_header = 'lmh'
    headers = {'If-Modified-Since': catalog.last_modified_header}
    response = self.mox.CreateMockAnything()
    response.status_code = 304

    url = applesus.CATALOGS.values()[0]

    applesus.urlfetch.fetch(
        url, headers=headers, deadline=deadline,
        validate_certificate=True).AndReturn(response)

    self.mox.ReplayAll()
    self.assertFalse(self.c._UpdateCatalogIfChanged(catalog, url))
    self.mox.VerifyAll()

  def testUpdateCatalogIfChangedWhenOtherStatusCode(self):
    """Test _UpdateCatalogIfChanged()."""
    self.mox.StubOutWithMock(applesus.urlfetch, 'fetch')
    self.mox.StubOutWithMock(self.c, '_UpdateCatalog')

    deadline = 30
    catalog = self.mox.CreateMockAnything()
    catalog.last_modified_header = 'lmh'
    headers = {'If-Modified-Since': catalog.last_modified_header}
    response = self.mox.CreateMockAnything()
    response.status_code = 404

    url = applesus.CATALOGS.values()[0]

    applesus.urlfetch.fetch(
        url, headers=headers, deadline=deadline,
        validate_certificate=True).AndReturn(response)

    self.mox.ReplayAll()
    self.assertRaises(
        applesus.urlfetch.DownloadError, self.c._UpdateCatalogIfChanged,
        catalog, url)
    self.mox.VerifyAll()

  def testUpdateProductDataFromCatalog(self):
    """Tests _UpdateProductDataFromCatalog()."""
    product_one_id = '1productid'
    product_one_url = 'http://example.com/%s.dist' % product_one_id
    product_two_id = '2productid'
    product_two_url = 'http://example.com/%s.dist' % product_one_id
    product_two_dist = {
        'version': 'twover', 'title': 'twotitle', 'description': 'twodesc'}
    product_three_id = '3productid'
    product_three_url = 'http://example.com/%s.dist' % product_three_id
    product_three_dist = {
        'version': 'threever', 'title': 'threetitle',
        'description': 'threedesc'
    }
    catalog = {
        'Products': {
            product_one_id: {
                'Distributions': {'English': product_one_url},
                'PostDate': 'onedate',
            },
            product_two_id: {
                'Distributions': {'English': product_two_url},
                'PostDate': 'twodate',
            },
            product_three_id: {
                'Distributions': {'en': product_three_url},
                'PostDate': 'threedate',
            },
        }
    }
    self.mox.StubOutWithMock(applesus.models.AppleSUSProduct, 'all')
    self.mox.StubOutWithMock(applesus.urllib2, 'urlopen')
    self.mox.StubOutWithMock(applesus.applesus, 'ParseDist')
    self.mox.StubOutWithMock(applesus.models, 'AppleSUSProduct')

    mock_urllib_return = self.mox.CreateMockAnything()
    mock_urllib_return.code = 200  # always return 200 for test.

    # product_one; add to existing_products so it's skipped.
    mock_existing_product = self.mox.CreateMockAnything()
    mock_existing_product.product_id = product_one_id
    existing_products = [mock_existing_product]
    applesus.models.AppleSUSProduct.all().AndReturn(existing_products)

    # product_two
    applesus.urllib2.urlopen(product_two_url).AndReturn(mock_urllib_return)
    mock_urllib_return.read().AndReturn(product_two_dist)
    applesus.applesus.ParseDist(product_two_dist).AndReturn(
        product_two_dist)
    mock_product_two = self.mox.CreateMockAnything()
    applesus.models.AppleSUSProduct(key_name=product_two_id).AndReturn(
        mock_product_two)
    mock_product_two.put().AndReturn(None)

    # product_three
    applesus.urllib2.urlopen(product_three_url).AndReturn(mock_urllib_return)
    mock_urllib_return.read().AndReturn(product_three_dist)
    applesus.applesus.ParseDist(product_three_dist).AndReturn(
        product_three_dist)
    mock_product_three = self.mox.CreateMockAnything()
    applesus.models.AppleSUSProduct(key_name=product_three_id).AndReturn(
        mock_product_three)
    mock_product_three.put().AndReturn(None)

    self.mox.ReplayAll()
    new_products = self.c._UpdateProductDataFromCatalog(catalog)
    self.assertEqual(new_products, [mock_product_two, mock_product_three])
    self.assertEqual(mock_product_two.name, 'twotitle')
    self.assertEqual(mock_product_two.apple_mtime, 'twodate')
    self.assertEqual(mock_product_three.version, 'threever')
    self.assertEqual(mock_product_three.description, 'threedesc')
    self.mox.VerifyAll()

  def testDeprecateOrphanedProducts(self):
    """Tests _DeprecateOrphanedProducts() with deprecated & active products."""
    # Stub in some modified catalogs/tracks variables.
    catalogs = applesus.CATALOGS.copy()
    catalogs['nonexistent'] = 'uselessurl'
    tracks = applesus.common.TRACKS + ['parseerror']
    self.stubs.Set(applesus, 'CATALOGS', catalogs)
    self.stubs.Set(applesus.common, 'TRACKS', tracks)

    self.mox.StubOutWithMock(applesus.plist, 'ApplePlist')
    self.mox.StubOutWithMock(applesus.models, 'AppleSUSProduct')
    self.mox.StubOutWithMock(applesus.models, 'AppleSUSCatalog')
    test_products = {
        '10.5_unstable': ['product1'],
        '10.5_testing': ['product1'],
        '10.5_stable': ['product1', 'product2'],
        '10.5_untouched': ['product1'],
        '10.6_unstable': ['product3'],
        '10.6_testing': ['product3', 'product4'],
        '10.6_stable': ['product3'],
        '10.6_untouched': ['product1'],
        '10.7_unstable': ['product5', 'product6'],
        '10.7_testing': ['product5'],
        '10.7_stable': ['product5'],
        '10.7_untouched': ['product7'],
        '10.8_unstable': ['product5', 'product6'],
        '10.8_testing': ['product5'],
        '10.8_stable': ['product5'],
        '10.8_untouched': ['product7'],
    }
    deprecated_products = []
    for p in ['product2', 'product3', 'product7', 'deprecateme', 'andme']:
      mock_product = self.mox.CreateMockAnything()
      mock_product.product_id = p
      deprecated_products.append(mock_product)

    for catalog in applesus.CATALOGS:
      for track in applesus.common.TRACKS + ['untouched']:
        key = '%s_%s' % (catalog, track)
        if catalog == 'nonexistent':
          applesus.models.AppleSUSCatalog.get_by_key_name(key).AndReturn(None)
          continue
        mock_p = self.mox.CreateMockAnything()
        mock_p.plist = 'fooplist-%s' % key
        applesus.models.AppleSUSCatalog.get_by_key_name(key).AndReturn(mock_p)
        mock_plist = self.mox.CreateMockAnything()
        mock_plist = applesus.plist.ApplePlist(mock_p.plist).AndReturn(
            mock_plist)
        if track == 'parseerror':
          mock_plist.Parse().AndRaise(applesus.plist.Error)
          continue
        mock_plist.Parse().AndReturn(None)
        mock_plist.get('Products', []).AndReturn(test_products[key])

    expected_deprecated_out = []
    mock_query = self.mox.CreateMockAnything()
    applesus.models.AppleSUSProduct.all().AndReturn(mock_query)
    mock_query.filter('deprecated =', False).AndReturn(deprecated_products)
    for deprecated_product in deprecated_products:
      # product<#> should not be removed/deprecated as they exist in catalogs.
      if deprecated_product.product_id in ['deprecateme', 'andme']:
        deprecated_product.put().AndReturn(None)
        expected_deprecated_out.append(deprecated_product)

    self.mox.ReplayAll()
    out = self.c._DeprecateOrphanedProducts()
    self.assertEqual(out, expected_deprecated_out)
    self.mox.VerifyAll()

  def testProcessCatalogAndNotifyAdmins(self):
    """Tests _ProcessCatalogAndNotifyAdmins()."""
    os_version = '10.7'
    mock_catalog = self.mox.CreateMockAnything()
    mock_catalog.plist = 'fooplist'

    new_products = ['new1', 'new2']
    deprecated_products = ['old1', 'old2']
    self.mox.StubOutWithMock(applesus.models.AdminAppleSUSProductLog, 'Log')
    self.mox.StubOutWithMock(applesus.plist, 'ApplePlist')
    self.mox.StubOutWithMock(self.c, '_UpdateProductDataFromCatalog')
    self.mox.StubOutWithMock(self.c, '_DeprecateOrphanedProducts')
    self.mox.StubOutWithMock(self.c, '_NotifyAdminsOfCatalogSync')
    self.mox.StubOutWithMock(applesus.applesus, 'GenerateAppleSUSCatalog')
    mock_plist = self.mox.CreateMockAnything()

    applesus.plist.ApplePlist(mock_catalog.plist).AndReturn(mock_plist)
    mock_plist.Parse().AndReturn(None)
    self.c._UpdateProductDataFromCatalog(mock_plist).AndReturn(new_products)
    self.c._DeprecateOrphanedProducts().AndReturn(deprecated_products)
    self.c._NotifyAdminsOfCatalogSync(
        mock_catalog, new_products, deprecated_products)

    applesus.applesus.GenerateAppleSUSCatalog(
        os_version, applesus.common.UNSTABLE).AndReturn(None)

    applesus.models.AdminAppleSUSProductLog.Log(
        new_products, 'new for %s' % os_version)
    applesus.models.AdminAppleSUSProductLog.Log(
        deprecated_products, 'deprecated for %s' % os_version)

    self.mox.ReplayAll()
    self.c._ProcessCatalogAndNotifyAdmins(mock_catalog, os_version)
    self.mox.VerifyAll()


class AppleSUSAutoPromoteTest(test.RequestHandlerTest):

  def GetTestClassInstance(self):
    return applesus.AppleSUSAutoPromote()

  def GetTestClassModule(self):
    return applesus

  def testGet(self):
    """Tests get()."""
    today = datetime.datetime.utcnow().date()
    mock_product_promote_testing= self.mox.CreateMockAnything()
    mock_product_promote_testing.tracks = ['unstable']
    mock_product_promote_testing.product_id = 'fooid'
    mock_product_promote_testing.manual_override = False
    mock_product_promote_testing.mtime = 'testingpromotetime'

    mock_product_toonew = self.mox.CreateMockAnything()
    mock_product_toonew.tracks = ['unstable']
    mock_product_toonew.product_id = 'fooid2'
    mock_product_toonew.manual_override = False
    mock_product_toonew.mtime = 'toonewtime'

    mock_product_promote_stable = self.mox.CreateMockAnything()
    mock_product_promote_stable.tracks = ['unstable', applesus.common.TESTING]
    mock_product_promote_stable.product_id = 'fooid3'
    mock_product_promote_stable.manual_override = False
    mock_product_promote_stable.mtime = 'stablepromotetime'

    testing_products = [mock_product_promote_testing, mock_product_toonew]
    stable_products = [mock_product_promote_stable]

    self.mox.StubOutWithMock(applesus.models.AppleSUSProduct, 'all')
    self.mox.StubOutWithMock(applesus.applesus, 'GenerateAppleSUSCatalogs')
    self.mox.StubOutWithMock(applesus.models.AdminAppleSUSProductLog, 'Log')
    self.mox.StubOutWithMock(applesus.applesus, 'GetAutoPromoteDate')

    promotions = {}

    mock_query = self.mox.CreateMockAnything()

    # testing promote
    applesus.models.AppleSUSProduct.all().AndReturn(mock_query)
    mock_query.filter('tracks !=', applesus.common.TESTING).AndReturn(
        testing_products)
    applesus.applesus.GetAutoPromoteDate(
        applesus.common.TESTING, mock_product_promote_testing).AndReturn(
            today)
    mock_product_promote_testing.put().AndReturn(None)
    promotions[applesus.common.TESTING] = [mock_product_promote_testing]

    # the testing product with too new of a datetime does not get promoted.
    applesus.applesus.GetAutoPromoteDate(
        applesus.common.TESTING, mock_product_toonew).AndReturn(
            today + datetime.timedelta(days=2))

    # stable promote
    applesus.models.AppleSUSProduct.all().AndReturn(mock_query)
    mock_query.filter('tracks !=', applesus.common.STABLE).AndReturn(
        stable_products)
    applesus.applesus.GetAutoPromoteDate(
        applesus.common.STABLE, mock_product_promote_stable).AndReturn(
            today - datetime.timedelta(days=3))
    mock_product_promote_stable.put().AndReturn(None)
    mock_log = self.mox.CreateMockAnything()
    promotions[applesus.common.STABLE] = [mock_product_promote_stable]

    for track in [applesus.common.TESTING, applesus.common.STABLE]:
      applesus.applesus.GenerateAppleSUSCatalogs(track)
      applesus.models.AdminAppleSUSProductLog.Log(
          promotions[track], 'auto-promote to %s' % track).AndReturn(None)

    self.mox.StubOutWithMock(self.c, '_NotifyAdminsOfAutoPromotions')
    self.c._NotifyAdminsOfAutoPromotions(promotions).AndReturn(None)

    self.mox.ReplayAll()
    self.c.get()

    self.assertTrue(
        applesus.common.TESTING in mock_product_promote_testing.tracks)
    self.assertTrue(
        applesus.common.STABLE not in mock_product_promote_testing.tracks)

    self.assertTrue(
        applesus.common.TESTING not in mock_product_toonew.tracks)
    self.assertTrue(
        applesus.common.STABLE not in mock_product_toonew.tracks)

    self.assertTrue(
        applesus.common.STABLE in mock_product_promote_stable.tracks)
    self.mox.VerifyAll()


def main(unused_argv):
  test.main(unused_argv)


if __name__ == '__main__':
  app.run()