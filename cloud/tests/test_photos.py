import io,json,tempfile,unittest,sys,hashlib,os
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.photos import crop_pixels,square_asset,synthetic_initials,decoded,revise_photo
from scotus_cloud.codex_auth import run_codex
from scotus_cloud.github_assets import portrait_files

class PhotoTests(unittest.TestCase):
    def image(self):
        im=Image.new('RGB',(300,600),'white');im.paste('#00aa00',(0,0,300,220));out=io.BytesIO();im.save(out,'PNG');return out.getvalue()

    def test_crop_is_square_and_does_not_silently_accept_invalid_coordinates(self):
        im=decoded(self.image());crop,box=crop_pixels(im,{'x':0,'y':0,'size':150},(150,300))
        self.assertEqual(crop.size,(300,300));self.assertEqual(box['y'],0)
        self.assertEqual(crop.getpixel((50,50)),(0,170,0))
        for invalid in ({'x':-1,'y':0,'size':50},{'x':0,'y':280,'size':100},{'x':0.5,'y':0,'size':100},{'x':0,'y':0,'size':0}):
            with self.assertRaises(ValueError):crop_pixels(im,invalid,(150,300))

    def test_large_portrait_is_downsampled_for_cropping(self):
        out=io.BytesIO();Image.new('RGB',(5383,3589),'white').save(out,'JPEG')
        image=decoded(out.getvalue())
        self.assertLessEqual(max(image.size),4096)
        self.assertAlmostEqual(image.width/image.height,5383/3589,places=3)

    @patch('scotus_cloud.photos.square_asset',return_value={'id':'proposed'})
    @patch('scotus_cloud.enrichment.fetch',return_value=b'owner image')
    @patch('scotus_cloud.photos.run_codex')
    def test_explicit_owner_image_goes_straight_to_crop_without_another_search(self,runner,fetch,crop):
        url='https://example.org/portrait.jpg';job={'id':'fixture','review':{'photos':{'test':{'name':'Test Advocate','candidates':[]}}}}
        with tempfile.TemporaryDirectory() as folder:
            choices=revise_photo({'person':'test','action':'different','hint':url},job,{},Mock(),Mock(),Path(folder))
        fetch.assert_called_once_with(url,4194304);runner.assert_not_called()
        self.assertEqual(choices,[{'id':'proposed'}]);self.assertEqual(crop.call_args.args[1]['origin'],'owner_url')

    @patch('scotus_cloud.photos.square_asset',side_effect=ValueError('No usable square crop: head outside image'))
    @patch('scotus_cloud.enrichment.fetch',return_value=b'owner image')
    def test_explicit_source_keeps_the_useful_crop_error(self,fetch,crop):
        job={'review':{'photos':{'test':{'name':'Test Advocate'}}}}
        with tempfile.TemporaryDirectory() as folder,self.assertRaisesRegex(ValueError,'head outside image'):
            revise_photo({'person':'test','action':'different','hint':'https://example.org/portrait.jpg'},job,{},Mock(),Mock(),Path(folder))

    def test_explicit_source_reports_http_failure(self):
        from urllib.error import HTTPError
        job={'review':{'photos':{'test':{'name':'Test Advocate'}}}}
        with tempfile.TemporaryDirectory() as folder,patch('scotus_cloud.enrichment.fetch',side_effect=HTTPError('https://example.org/image',403,'Forbidden',{},None)),self.assertRaisesRegex(ValueError,'HTTP 403'):
            revise_photo({'person':'test','action':'different','hint':'https://example.org/image'},job,{},Mock(),Mock(),Path(folder))

    @patch('scotus_cloud.photos.run_codex')
    def test_model_sees_photo_and_applies_its_box_while_retaining_original(self,runner):
        runner.return_value={'usable':True,'x':0,'y':0,'size':300,'private_note':'Leave room above the head.'}
        cloud=Mock();cloud.storage_upload.return_value=None
        raw=self.image();job={'id':'fixture'};settings={'bucket':'private','codex_secret':'private-auth'}
        with tempfile.TemporaryDirectory() as folder:
            choice=square_asset(raw,{'kind':'photo','name':'Test Advocate'},(Mock(),cloud,settings,job,'test'),Path(folder))
            self.assertEqual((Path(folder)/'original.bin').read_bytes(),raw)
            self.assertEqual(decoded((Path(folder)/'portrait.jpg').read_bytes()).size,(300,300))
        args=runner.call_args.kwargs
        self.assertEqual(args['images'],['input/photo.jpg']);self.assertIn('input/photo.jpg',args['inputs'])
        self.assertEqual(choice['source_sha256'],hashlib.sha256(raw).hexdigest());self.assertTrue(choice['square_asset'])
        self.assertEqual(choice['crop']['method'],'codex-vision');self.assertEqual(choice['crop']['y'],0)

    @patch('scotus_cloud.photos.run_codex')
    def test_unsuitable_source_never_becomes_an_approved_candidate(self,runner):
        runner.return_value={'usable':False,'x':0,'y':0,'size':1,'private_note':'The head is outside the original image.'}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):square_asset(self.image(),{'kind':'photo'},(Mock(),Mock(),{'bucket':'private','codex_secret':'auth'},{'id':'fixture'},'test'),Path(folder))

    def test_initials_are_a_square_graphic(self):
        image=synthetic_initials('JW');self.assertEqual(decoded(image).size,(1024,1024))
        files=portrait_files('j_w_test','jpg',image,{'identity_verified':True,'name':'Test Advocate','docket':'25-735','kind':'initials','synthetic':{'type':'initials','text':'JW'},'identity_source_url':'https://www.supremecourt.gov/docket'})
        self.assertIn('advocates/j_w_test.jpg',files)
        for invalid in ('','ABCDE','<svg>'):
            with self.assertRaises(ValueError):synthetic_initials(invalid)

    @patch('scotus_cloud.photos.run_codex')
    @patch('scotus_cloud.enrichment.fetch',return_value=b'Official docket identity evidence')
    def test_owner_hint_reaches_research_without_worker_tokens(self,fetch,runner):
        runner.return_value={'candidates':[{'url':'','source_url':'','identity_source_url':'','kind':'initials','initials':'JW','private_note':'Owner requested initials.'}],'private_note':''}
        candidate={'id':'old','kind':'photo','rejected':True,'source_url':'https://example.org/old'}
        job={'id':'fixture','docket':'25-735','review':{'photos':{'test':{'name':'Test Advocate','candidates':[candidate]}}}}
        request={'person':'test','candidate':'old','action':'synthetic','hint':'Use initials please','lease':'secret-worker-token','dispatch_token':'secret-dispatch-token'}
        with tempfile.TemporaryDirectory() as folder:
            choices=revise_photo(request,job,{'bucket':'private','codex_secret':'auth'},Mock(),Mock(),Path(folder))
        model_input=runner.call_args.kwargs['inputs']['input/request.json']
        self.assertIn('Use initials please',model_input);self.assertNotIn('secret-worker-token',model_input);self.assertNotIn('secret-dispatch-token',model_input)
        self.assertEqual(choices[0]['kind'],'initials');self.assertTrue(choices[0]['square_asset'])

    @patch.dict(os.environ,{'SCOTUS_PRIVATE_CODEX_WORKER':'1'})
    def test_cli_image_paths_cannot_point_outside_supplied_input_files(self):
        dashboard=Mock()
        with self.assertRaises(ValueError):run_codex(dashboard,Mock(),'auth','prompt',{},inputs={'input/photo.jpg':b'image'},images=['/secrets/auth.json'])
        dashboard.call.assert_not_called()

if __name__=='__main__':unittest.main()
